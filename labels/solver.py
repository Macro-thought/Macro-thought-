#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.4 确定性求解器（应然标签的唯一来源）
======================================
`gold = Solve(Q, G)`：给定结构化查询 Q 与一张图 G，返回**唯一确定**的答案。

设计约束（评审 §2，写进任务书 §6.1 的那条）：
  **本文件不得 import ops/、baselines/ 的任何东西**，也不得复用它们的图访问代码。
  它与被测系统的唯一共享物是「同一份图数据」。这一点由 scripts/verify_labels.py
  用 AST 扫描强制检查，不靠自觉。

语义约定（这是「应然」的定义，不是实现细节，论文方法节必须写）：
  - 类的实例集 = **闭包**（自身 + 所有后代类 P279*）。这是 OWL 子类语义，
    也是我们判定"细化/拆分后答案该不该变"的依据。
  - 计数一律 distinct 实体；枚举答案按实体 id 排序后取中文标签，保证可比。
  - 关系查询只看当前版本（v2 的退休边在文件里已移出 edges，不进索引）。

用法：
    python labels/solver.py --smoke              # 全部 5 个分支，产出 qa_smoke.jsonl
    python labels/solver.py --graph data/graph_v2_split.json --q Q001
"""

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

BRANCHES = {
    # branch -> (v1 基线图, v2 图)
    "refine": ("graph_v1.json", "graph_v2_refine.json"),
    "restrict": ("graph_v1.json", "graph_v2_restrict.json"),
    "merge": ("graph_v1_mb.json", "graph_v2_merge.json"),
    "split": ("graph_v1.json", "graph_v2_split.json"),
    "all": ("graph_v1_mb.json", "graph_v2_all.json"),
}


# ---------------------------------------------------------------- 图访问（独立实现）

class Kg:
    def __init__(self, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.ents = {e["id"]: e for e in d["entities"]}
        self.out = collections.defaultdict(list)      # (h) -> [(r, t)]
        self.p31 = collections.defaultdict(set)       # class -> {inst}
        self.kids = collections.defaultdict(set)      # parent -> {child}
        for e in d["edges"]:
            self.out[e["h"]].append((e["r"], e["t"]))
            if e["r"] == "P31":
                self.p31[e["t"]].add(e["h"])
            elif e["r"] == "P279":
                self.kids[e["t"]].add(e["h"])
        self._closure = {}

    def closure(self, c):
        """类的实例闭包。用迭代到不动点实现（与被测系统递归 BFS 不同，避免同源）。"""
        if c in self._closure:
            return self._closure[c]
        desc, frontier = {c}, [c]
        while frontier:
            nxt = []
            for x in frontier:
                for k in self.kids.get(x, ()):
                    if k not in desc:
                        desc.add(k)
                        nxt.append(k)
            frontier = nxt
        s = set()
        for d in desc:
            s |= self.p31.get(d, set())
        self._closure[c] = s
        return s

    def tails(self, h, r):
        return {t for (rr, t) in self.out.get(h, ()) if rr == r}

    def label(self, i):
        return (self.ents.get(i) or {}).get("label_zh") or i

    def country(self, i):
        return (self.ents.get(i) or {}).get("country")


# ---------------------------------------------------------------- 查询语义

def solve(g, q):
    op = q["op"]
    if op == "count_class":
        return {"type": "int", "value": len(g.closure(q["class"]))}
    if op == "count_class_country":
        return {"type": "int",
                "value": sum(1 for x in g.closure(q["class"])
                             if g.country(x) == q["country"])}
    if op == "count_rel":
        return {"type": "int", "value": len(g.tails(q["head"], q["rel"]))}
    if op == "list_rel":
        ids = sorted(g.tails(q["head"], q["rel"]))
        return {"type": "set", "value": [g.label(i) for i in ids]}
    if op == "list_class":
        ids = sorted(g.closure(q["class"]))
        return {"type": "set", "value": [g.label(i) for i in ids]}
    if op == "count_with_rel":
        return {"type": "int",
                "value": sum(1 for x in g.closure(q["class"]) if g.tails(x, q["rel"]))}
    if op == "universal_rel":
        inst = g.closure(q["class"])
        return {"type": "bool", "value": bool(inst) and all(g.tails(x, q["rel"]) for x in inst)}
    if op == "hop2_head":
        vals = set()
        for mid in g.tails(q["head"], q["rel1"]):
            vals |= g.tails(mid, q["rel2"])
        return {"type": "int", "value": len(vals)}
    if op == "hop2_distinct":
        vals = set()
        for x in g.closure(q["class"]):
            for mid in g.tails(x, q["rel1"]):
                vals |= g.tails(mid, q["rel2"])
        return {"type": "int", "value": len(vals)}
    raise ValueError(f"未知查询类型 {op}")


def _empty(a):
    return (a["type"] == "int" and a["value"] == 0) or (a["type"] == "set" and not a["value"])


def should_of(a, b):
    """
    应然三分类。判据是「答案是否变化」，不是「哪个答案对」。
      stable       两版相同
      unanswerable v1 有答案、v2 已成空（问题在新图上不可答）
      flip         其余一切变化
    """
    if a == b:
        return "stable"
    if _empty(b) and not _empty(a):
        return "unanswerable"
    return "flip"


# ---------------------------------------------------------------- 主流程

def run_branch(branch, qs):
    v1f, v2f = BRANCHES[branch]
    g1, g2 = Kg(DATA / v1f), Kg(DATA / v2f)
    rows = []
    for q in qs:
        a, b = solve(g1, q["query"]), solve(g2, q["query"])
        rows.append({
            "qid": q["qid"], "branch": branch, "shape": q["shape"],
            "question": q["nl"], "template": q.get("template"), "query": q["query"],
            "gold_v1": a, "gold_v2": b, "should": should_of(a, b),
            "v1_graph": v1f, "v2_graph": v2f,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--questions", default=None, help="题集文件，默认 questions_smoke.json")
    ap.add_argument("--out", default=None, help="输出 jsonl，默认 qa_smoke.jsonl")
    ap.add_argument("--graph")
    ap.add_argument("--q")
    args = ap.parse_args()

    qfile = Path(args.questions) if args.questions else DATA / "questions_smoke.json"
    if not qfile.exists():
        print(f"缺 {qfile}", file=sys.stderr)
        return 2
    pack = json.loads(qfile.read_text(encoding="utf-8"))
    qs = pack["questions"]

    if args.graph:
        g = Kg(args.graph)
        for q in qs:
            if args.q and q["qid"] != args.q:
                continue
            print(q["qid"], q["nl"], "→", json.dumps(solve(g, q["query"]), ensure_ascii=False))
        return 0

    out = []
    for branch in BRANCHES:
        rows = run_branch(branch, qs)
        out += rows
        n = collections.Counter(r["should"] for r in rows)
        print(f"  {branch:9s} stable {n['stable']:2d} / flip {n['flip']:2d} / "
              f"unanswerable {n['unanswerable']:2d}")

    path = Path(args.out) if args.out else DATA / "qa_smoke.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out), encoding="utf-8")

    # 15 格矩阵（计数/枚举/是-否 三形 × 五行），hop2 单列
    core = ["count", "set", "bool"]
    print("\n应然矩阵（stable / flip / unanswerable）")
    print("| 分支 | " + " | ".join(core) + " | hop2 |")
    print("|---" * (len(core) + 2) + "|")
    for branch in BRANCHES:
        cells = []
        for shape in core:
            sub = [r for r in out if r["branch"] == branch and r["shape"] == shape]
            c = collections.Counter(r["should"] for r in sub)
            cells.append(f"{c['stable']}/{c['flip']}/{c['unanswerable']}")
        sub = [r for r in out if r["branch"] == branch and r["shape"] == "hop2"]
        c = collections.Counter(r["should"] for r in sub)
        cells.append(f"{c['stable']}/{c['flip']}/{c['unanswerable']}")
        print(f"| {branch} | " + " | ".join(cells) + " |")

    try:
        shown = path.resolve().relative_to(ROOT)
    except ValueError:
        shown = path
    print(f"\n写出 {shown}（{len(out)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
