#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.3 四个 schema 算子 → 七份图（v1 + v1_mb + 5 份 v2）
==============================
输入：data/graph_v1.json（只读，绝不修改）+ data/schema.json（T1.2 的操作计划）
输出：data/graph_v1_mb.json（merge 分支的合成基线）
      data/graph_v2_{refine,restrict,merge,split,all}.json

四个算子的语义（写死在代码里，报告里同步说明）：

  REFINE_TYPE  最具体类型化：实例若同时断言 C 与 C 的后代 D，删除指向 C 的断言。
               形式保证：C 的实例闭包不变（叶子匹配会变，这正是要测的东西）。
  SPLIT_CONCEPT C 拆为 P（真实子类）+ C'（补集，合成类，P279→C）；负分支实例迁移到 C'。
               形式保证：互斥、并集 = v1 闭包。
  RESTRICT_REL R 的扩展收窄到满足条件的边；不满足的边退休（不是删除，进 retired 可审计）。
               形式保证：v2 中不存在违反条件的 R 边。
  MERGE_ENTITY 合成重复节点合并回主节点：边重定向、去重、节点标记 merged_into。
               形式保证：边不丢失（重定向后可追），无 dup 节点残留。

确定性：所有输出在写盘前对 (entities, edges) 做稳定排序，再算 sha1 指纹；
同一输入连跑两次指纹必须一致——这是 G2 闸门的判据。

    python ops/apply_ops.py --all
    python ops/apply_ops.py --only refine
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1 = ROOT / "data" / "graph_v1.json"
SCHEMA = ROOT / "data" / "schema.json"
DATA = ROOT / "data"

EDGE_FIELDS = ["h", "r", "t", "source", "version", "valid_from", "valid_to",
               "superseded_by", "id", "why"]


# ---------------------------------------------------------------- 基础设施

def edge_id(h, r, t):
    """稳定 id：三元组的 sha1 前 12 位。同一三元组在任何图里 id 相同，便于跨版本对齐。"""
    return "e:" + hashlib.sha1(f"{h}|{r}|{t}".encode("utf-8")).hexdigest()[:12]


def norm_edges(edges):
    out = []
    for e in edges:
        x = {k: e.get(k) for k in EDGE_FIELDS}
        x["id"] = x["id"] or edge_id(e["h"], e["r"], e["t"])
        x["why"] = x.get("why") or "carried_from_v1"
        out.append(x)
    out.sort(key=lambda e: (e["h"], e["r"], e["t"]))
    return out


def fingerprint(ents, edges):
    h = hashlib.sha1()
    for e in sorted(ents, key=lambda x: x["id"]):
        h.update(("E|" + e["id"] + "|" + (e.get("label_zh") or "")).encode("utf-8"))
    for e in edges:
        h.update(("R|" + e["h"] + "|" + e["r"] + "|" + e["t"]).encode("utf-8"))
    return h.hexdigest()[:16]


class Graph:
    def __init__(self, d):
        self.meta = dict(d["meta"])
        self.entities = {e["id"]: dict(e) for e in d["entities"]}
        self.edges = norm_edges(d["edges"])
        self.retired = []
        self.changes = []

    def clone(self):
        g = Graph({"meta": self.meta, "entities": [], "edges": self.edges})
        g.entities = {k: dict(v) for k, v in self.entities.items()}
        g.retired = [dict(x) for x in self.retired]
        g.changes = [dict(x) for x in self.changes]
        return g

    # ---- 图访问
    def out_edges(self, h, r=None):
        return [e for e in self.edges if e["h"] == h and (r is None or e["r"] == r)]

    def children(self, c):
        return [e["h"] for e in self.edges if e["r"] == "P279" and e["t"] == c]

    def descendants(self, c):
        seen, stack = set(), [c]
        while stack:
            x = stack.pop()
            for k in self.children(x):
                if k not in seen:
                    seen.add(k)
                    stack.append(k)
        return seen

    def types_of(self, x):
        return {e["t"] for e in self.edges if e["r"] == "P31" and e["h"] == x}

    def closure(self, c):
        s = {e["h"] for e in self.edges if e["r"] == "P31" and e["t"] == c}
        for d in self.descendants(c):
            s |= {e["h"] for e in self.edges if e["r"] == "P31" and e["t"] == d}
        return s

    def drop_edges(self, pred, op, why, extra=None):
        keep, gone = [], []
        for e in self.edges:
            (gone if pred(e) else keep).append(e)
        for e in gone:
            e = dict(e)
            e["why"] = why
            if extra:
                e.update(extra)
            self.retired.append(e)
            self.changes.append({"op": op, "kind": "retire_edge", "edge_id": e["id"],
                                 "triple": f"{e['h']}-{e['r']}-{e['t']}", "why": why})
        self.edges = keep
        return gone

    def add_edge(self, h, r, t, op, why, **kw):
        e = {"h": h, "r": r, "t": t, "source": r, "version": self.meta["version"],
             "valid_from": None, "valid_to": None, "superseded_by": None,
             "id": edge_id(h, r, t), "why": why}
        e.update(kw)
        if any(x["id"] == e["id"] for x in self.edges):
            return None
        self.edges.append(e)
        self.changes.append({"op": op, "kind": "add_edge", "edge_id": e["id"],
                             "triple": f"{h}-{r}-{t}", "why": why})
        return e


def load_v1():
    d = json.loads(V1.read_text(encoding="utf-8"))
    return Graph(d)


# ---------------------------------------------------------------- 四个算子

def op_refine(g, plan):
    """最具体类型化。"""
    c = plan["target"]
    desc = g.descendants(c)
    targets = [x for x in g.closure(c) if g.types_of(x) & desc]
    ids = {edge_id(x, "P31", c) for x in targets}
    gone = g.drop_edges(lambda e: e["id"] in ids and e["r"] == "P31" and e["t"] == c,
                        "REFINE_TYPE", f"实例已断言 {c} 的后代，父类断言冗余（最具体类型化）")
    return {"op": "REFINE_TYPE", "n_removed": len(gone), "target": c}


def op_split(g, plan):
    """C → {P（真实子类）, C'（补集，合成）}；负分支实例迁移。"""
    c = plan["target"]
    p = plan["positive"]["qid"]
    pos = g.closure(p)
    universe = g.closure(c)
    neg = universe - pos

    cq = plan["complement"]["qid"]
    if cq not in g.entities:
        g.entities[cq] = {
            "id": cq, "label_zh": plan["complement"]["label"], "label_en": None,
            "lang_source": "synthetic", "type": "未标注", "type_qids": [],
            "country": None, "aliases": [], "is_seed": False,
            "synthetic": True,
            "synthetic_note": "SPLIT_CONCEPT 的补集类，Wikidata 无此类，论文须标注",
        }
        g.changes.append({"op": "SPLIT_CONCEPT", "kind": "add_class", "edge_id": None,
                          "triple": cq, "why": "补集类"})
    g.add_edge(cq, "P279", c, "SPLIT_CONCEPT", "补集类归入父类，维持闭包不变")

    for x in sorted(neg):
        # 把「x P31 C」换成「x P31 C'」
        g.drop_edges(lambda e, x=x: e["r"] == "P31" and e["h"] == x and e["t"] == c,
                     "SPLIT_CONCEPT", f"实例迁入补集类 {cq}")
        g.add_edge(x, "P31", cq, "SPLIT_CONCEPT", "SPLIT_CONCEPT：负分支迁移")
    return {"op": "SPLIT_CONCEPT", "n_migrated": len(neg),
            "positive": plan["positive"]["qid"], "complement": cq}


def op_restrict(g, plan):
    """关系收窄；不满足条件的边退休（保留在 retired 里可审计）。"""
    r = plan["relation"]
    cond_country = plan["condition"].split("==")[-1].strip()
    cond_country = cond_country.split("（")[0].strip()
    keep = []
    for e in g.edges:
        if e["r"] != r:
            keep.append(e)
            continue
        tail = g.entities.get(e["t"], {})
        if tail.get("country") == cond_country:
            keep.append(e)
    ids_keep = {e["id"] for e in keep}
    gone = g.drop_edges(lambda e: e["r"] == r and e["id"] not in ids_keep,
                        "RESTRICT_REL",
                        f"关系收窄：tail.country != {cond_country}，该边退出当前扩展",
                        extra={"valid_to": "2024"})
    return {"op": "RESTRICT_REL", "n_retired": len(gone), "relation": r}


def build_merge_base(g, plan):
    """v1 分支基线：把每个待合并实体的 label_en 拆成独立节点（合成重复）。"""
    for pair in plan["pairs"]:
        keep, dup = pair["keep"], pair["drop"]
        if dup in g.entities:
            continue
        src = g.entities[keep]
        g.entities[dup] = {
            "id": dup, "label_zh": pair["drop_label"], "label_en": pair["drop_label"],
            "lang_source": "synthetic_en", "type": src.get("type"),
            "type_qids": list(src.get("type_qids") or []), "country": src.get("country"),
            "aliases": [src["label_zh"]], "is_seed": False,
            "synthetic": True,
            "synthetic_note": "MERGE_ENTITY 的合成重复节点：同一实体以英文名单独入库",
        }
        for e in list(g.edges):
            if e["h"] == keep:
                g.add_edge(dup, e["r"], e["t"], "MERGE_BASE",
                           f"合成重复节点的出边（源 {keep}）")
    g.meta["version"] = "v1_mb"
    return g


def op_merge(g, plan):
    """合并：边重定向到主节点，去重，节点标记 merged_into。"""
    n_redirect = 0
    for pair in plan["pairs"]:
        keep, dup = pair["keep"], pair["drop"]
        if dup not in g.entities:
            continue
        for e in list(g.edges):
            if e["h"] == dup:
                g.drop_edges(lambda x, e=e: x["id"] == e["id"], "MERGE_ENTITY",
                             f"{dup} 并入 {keep}：出边重定向")
                if g.add_edge(keep, e["r"], e["t"], "MERGE_ENTITY",
                              f"{dup} 并入 {keep}：出边重定向",
                              superseded_by=None):
                    n_redirect += 1
        for e in g.edges:
            if e["h"] == keep and e["t"] == dup:
                e["t"] = keep
            if e["h"] == dup and e["t"] == keep:
                pass
        g.entities[dup]["merged_into"] = keep
        del g.entities[dup]
        g.changes.append({"op": "MERGE_ENTITY", "kind": "merge_node", "edge_id": None,
                          "triple": f"{dup}->{keep}", "why": "同指实体归一"})
    return {"op": "MERGE_ENTITY", "n_redirected": n_redirect, "n_pairs": len(plan["pairs"])}


# ---------------------------------------------------------------- 落盘

def _keep_built_at(path, fp):
    """
    指纹不变则沿用旧的 built_at。

    为什么：旧版每次都写 now()，语义没变但文件字节全变，
    `git status` 永远脏、审计复跑也无法证明「这次运行没有改变任何产物」。
    只在内容真的变了（指纹变化）时才刷新时间戳。
    """
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8")).get("meta", {})
            if prev.get("idempotent_hash") == fp and prev.get("built_at"):
                return prev["built_at"]
        except Exception:                                          # noqa: BLE001
            pass
    return datetime.now().isoformat(timespec="seconds")


def save(g, version, path, ops):
    g.meta = dict(g.meta)
    g.meta["version"] = version
    g.meta["built_from"] = "data/graph_v1.json"
    g.meta["ops_applied"] = ops
    g.meta["n_entities"] = len(g.entities)
    g.meta["n_edges"] = len(g.edges)
    g.meta["n_retired"] = len(g.retired)
    ents = sorted(g.entities.values(), key=lambda e: e["id"])
    edges = norm_edges(g.edges)
    fp = fingerprint(ents, edges)
    g.meta["built_at"] = _keep_built_at(path, fp)
    g.meta["idempotent_hash"] = fp
    doc = {"meta": g.meta, "entities": ents, "edges": edges,
           "retired_edges": sorted(g.retired, key=lambda e: e["id"]),
           "changes": sorted(g.changes, key=lambda c: (c["op"], c["kind"], str(c["edge_id"])))}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  → {path.relative_to(ROOT)}  实体 {len(ents)} / 边 {len(edges)} / "
          f"退休 {len(g.retired)} / 指纹 {g.meta['idempotent_hash']}")
    return g.meta["idempotent_hash"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", default=None,
                    choices=["refine", "restrict", "merge", "split", "base"])
    args = ap.parse_args()
    if not (args.all or args.only):
        ap.error("指定 --all 或 --only")

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    plan = schema["ops_plan"]
    want = ["refine", "restrict", "merge", "split"] if args.all else [args.only]

    # merge 分支的基线（v1_mb）总要单独落盘，供 T1.4 使用
    base = load_v1()
    mb = build_merge_base(base.clone(), plan["merge_entity"])
    save(mb, "v1_mb", DATA / "graph_v1_mb.json", ["MERGE_BASE"])

    if "refine" in want:
        g = load_v1()
        op_refine(g, plan["refine_type"])
        save(g, "v2_refine", DATA / "graph_v2_refine.json", ["REFINE_TYPE"])
    if "restrict" in want:
        g = load_v1()
        op_restrict(g, plan["restrict_rel"])
        save(g, "v2_restrict", DATA / "graph_v2_restrict.json", ["RESTRICT_REL"])
    if "merge" in want:
        g = build_merge_base(load_v1(), plan["merge_entity"])
        op_merge(g, plan["merge_entity"])
        save(g, "v2_merge", DATA / "graph_v2_merge.json", ["MERGE_BASE", "MERGE_ENTITY"])
    if "split" in want:
        g = load_v1()
        op_split(g, plan["split_concept"])
        save(g, "v2_split", DATA / "graph_v2_split.json", ["SPLIT_CONCEPT"])
    if args.all:
        g = build_merge_base(load_v1(), plan["merge_entity"])
        for fn, key in [(op_merge, "merge_entity"), (op_refine, "refine_type"),
                        (op_split, "split_concept"), (op_restrict, "restrict_rel")]:
            fn(g, plan[key])
        save(g, "v2_all", DATA / "graph_v2_all.json",
             ["MERGE_BASE", "MERGE_ENTITY", "REFINE_TYPE", "SPLIT_CONCEPT", "RESTRICT_REL"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
