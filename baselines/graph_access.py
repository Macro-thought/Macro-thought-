#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一图访问层（叶子模块）
========================
B1/B2 共用同一套"图长什么样"的定义。单独成层的理由：两条基线之间唯一允许的差异
必须是「检索是否有损」，不能混入"边的方向、去重、排序、退休边怎么处理"这类实现细节；
把这些约定钉在一个文件里，两边的差异才可归因。

三条硬约定（论文方法节要写的东西）
  1. **只用 edges 数组**。`retired_edges` 是审计用的历史边，不属于当前图；
     基线如果去读它，等于让被测系统看到"已经不属于该版本的事实"，实验作废。
     需要做消融时才通过 `retired_of()` 显式取。
  2. **边 id 重算而非 import**。`ops/apply_ops.py` 用 sha1(h|r|t)[:12] 生成 id，
     但 v1 图里根本没有 `id` 字段（v1 是外部取回的原始图），v2 才有。这里重算同一公式
     （不 import ops/，AST 检查禁止），好处是同一三元组在 v1 与 v2 里 id 相同，
     B2 的 evidence 才能跨版本对齐比较——这是本研究的观测量之一。
  3. **顺序确定**。实体按 id、边按 (h,r,t) 排序后建邻接表，邻居顺序即由此固定。
     BM25 打平、BFS 截断都依赖这个顺序，否则 temperature=0 也复现不了。

本模块是叶子：只 import 标准库。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# 关系的中文名。只用于 verbalize（把边读成人话），不是"给 LLM 的白名单提示"：
# LLM 看到的永远是具体的邻域事实，而不是"你可以用哪些关系"。
R_LABEL = {
    "P31": "类型",
    "P17": "国家",
    "P279": "上级类",
    "P113": "航空枢纽",
    "P121": "运营机型",
    "P749": "母公司",
    "P159": "总部",
    "P127": "所属集团",
}


def edge_id(h: str, r: str, t: str) -> str:
    """稳定 id：三元组的 sha1 前 12 位。与 ops/apply_ops.py 的公式一致（重算，不 import）。"""
    return "e:" + hashlib.sha1(f"{h}|{r}|{t}".encode("utf-8")).hexdigest()[:12]


def r_label(r: str) -> str:
    return R_LABEL.get(r, r)  # 未知关系退化显示 QID 代码，不猜测语义


def version_family(v) -> str:
    """把 meta.version（v1 / v1_mb / v2_split / v2_all …）归到 v1 或 v2。

    输出格式里的 `version` 字段只有 v1/v2 两档（冻结字段），分支名在 meta.graph 里区分。
    """
    return "v2" if str(v).startswith("v2") else "v1"


def read_version(path) -> str:
    """只读 meta.version，不建图。给"不需要图但需要填输出字段"的基线（B1）用。"""
    with open(path, "r", encoding="utf-8") as f:
        meta = json.load(f).get("meta", {})
    return version_family(meta.get("version", ""))


class Graph:
    """单版本只读图。构造时把所有索引建好，查询全是 O(度数)。"""

    def __init__(self, entities, edges, retired=None, meta=None, path=None):
        self.path = Path(path) if path else None
        self.meta = dict(meta or {})
        self.version_raw = str(self.meta.get("version", ""))
        self.version = version_family(self.version_raw)

        self.entities = {}
        for e in sorted(entities, key=lambda x: x["id"]):
            self.entities[e["id"]] = e

        # 同三元组只留一条：id 由三元组派生，重复边在语义上是同一条事实。
        seen = set()
        self.edges = []
        for e in sorted(edges, key=lambda x: (x["h"], x["r"], x["t"])):
            eid = e.get("id") or edge_id(e["h"], e["r"], e["t"])
            if eid in seen:
                continue
            seen.add(eid)
            self.edges.append({
                "h": e["h"], "r": e["r"], "t": e["t"], "id": eid,
                "source": e.get("source"), "why": e.get("why"),
            })
        self._ids = seen

        self._out = {}
        self._in = {}
        for e in self.edges:  # self.edges 已按 (h,r,t) 排序 → 邻接表天然有序
            self._out.setdefault(e["h"], []).append((e["r"], e["t"], e["id"]))
            self._in.setdefault(e["t"], []).append((e["r"], e["h"], e["id"]))
        for k in self._in:
            self._in[k].sort(key=lambda x: (x[0], x[1]))

        # 退休边：不进任何查询路径，只给消融留口子。
        self.retired = sorted(retired or [], key=lambda e: (e["h"], e["r"], e["t"]))

    # ------------------------------------------------------------ 构造

    @classmethod
    def load(cls, path) -> "Graph":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls(d.get("entities", []), d.get("edges", []),
                   d.get("retired_edges"), d.get("meta"), path)

    # ------------------------------------------------------------ 查询

    def neighbors(self, h, r=None, version=None):
        """出边邻居 [(r, t)]。

        `version` 只做一致性校验，**不参与过滤**：v2 图里"承载自理"的边仍标注
        version="v1"（见 graph_v2_*.json 的 why=carried_from_v1），按 version 过滤会
        静默丢掉大半张图。图对象本身就已经是某一个版本了。
        """
        if version is not None and version_family(version) != self.version:
            return []
        return [(rr, tt) for (rr, tt, _) in self._out.get(h, []) if r is None or rr == r]

    def tails(self, h, r):
        """h 沿关系 r 的出边尾实体 id 列表（去重、按 id 排序）。"""
        ts = {tt for (rr, tt, _) in self._out.get(h, []) if rr == r}
        return sorted(ts)

    def heads(self, t, r=None):
        hs = {hh for (rr, hh, _) in self._in.get(t, []) if r is None or rr == r}
        return sorted(hs)

    def out_edges(self, h):
        """[(r, t, id)]，带 evidence id。B2 需要 id，故与 neighbors 并存。"""
        return list(self._out.get(h, []))

    def in_edges(self, t):
        return list(self._in.get(t, []))

    def incident(self, n):
        """无向邻接：[(r, other, id, dir)]，dir ∈ {"out","in"}，出边在前、入边在后。

        B2 用到它：问题既可能"从类找实例"（入边）也可能"从实体找属性"（出边），
        基线不知道算子类型，所以两个方向都扩——这本身也是"有损"的一部分。
        """
        return ([(r, t, i, "out") for (r, t, i) in self._out.get(n, [])]
                + [(r, h, i, "in") for (r, h, i) in self._in.get(n, [])])

    def label(self, i) -> str:
        e = self.entities.get(i)
        if not e:
            return i          # 查不到就退回 QID，不编造中文名
        return e.get("label_zh") or i

    def has_edge(self, eid) -> bool:
        return eid in self._ids

    def closure(self, class_id) -> set:
        """P279 后代闭包（**不含自身**）。

        方向注意：`X P279 C` 表示 X 是 C 的子类，所以"C 的后代"要沿 **入边** 走。
        本方法只服务消融/对照；B2 明确禁止用它做推理（那是 gold 的语义，用了就没有"有损"了）。
        """
        seen = set()
        stack = [class_id]
        while stack:
            c = stack.pop()
            for (r, h, _eid) in self._in.get(c, []):
                if r != "P279" or h in seen or h == class_id:
                    continue
                seen.add(h)
                stack.append(h)
        return seen

    def retired_of(self, h, r):
        """消融用：某 (h,r) 在历史版本里存在、当前已退休的边。不进当前图。"""
        return [e for e in self.retired if e["h"] == h and e["r"] == r]

    def __len__(self):
        return len(self.edges)

    def __repr__(self):
        return f"<Graph {self.version_raw} ents={len(self.entities)} edges={len(self.edges)}>"


if __name__ == "__main__":  # 手工体检：python baselines/graph_access.py data/graph_v1.json
    import sys
    g = Graph.load(sys.argv[1] if len(sys.argv) > 1 else "data/graph_v1.json")
    print(g, "retired:", len(g.retired))
    print("Q291090 的枢纽:", [g.label(t) for t in g.tails("Q291090", "P113")])
    print("Q46970 后代类数:", len(g.closure("Q46970")))
