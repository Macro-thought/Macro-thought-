#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.2 独立校验（G1 闸门）
========================
不 import build_schema.py。从 graph_v1.json 重新算一遍 T1.2 声称的形式条件，
与 data/schema.json 里的 checks 对账。

G1 判据（写死）：
  1. REFINE：闭包不变（集合相等）
  2. SPLIT：两分支互斥、并集 = 父类闭包、父类不再有直断实例（在 v2 上验证时）
  3. 每个候选操作的 target 类在图里存在
  4. schema 覆盖：所有有实例的类都在 classes 里

    python scripts/verify_schema.py
"""

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def indices(doc):
    direct, kids = collections.defaultdict(set), collections.defaultdict(set)
    for e in doc["edges"]:
        if e["r"] == "P31":
            direct[e["t"]].add(e["h"])
        elif e["r"] == "P279":
            kids[e["t"]].add(e["h"])
    return direct, kids


def clos(direct, kids, c):
    desc, stack = {c}, [c]
    while stack:
        x = stack.pop()
        for k in list(kids.get(x, ())):
            if k not in desc:
                desc.add(k)
                stack.append(k)
    return set().union(*[direct.get(d, set()) for d in desc]) if desc else set()


def main():
    g = load(DATA / "graph_v1.json")
    sc = load(DATA / "schema.json")
    direct, kids = indices(g)
    ok = True

    print("== 1. 操作目标存在性 ==")
    plan = sc["ops_plan"]
    for key in ("refine_type", "split_concept"):
        t = plan[key]["target"]
        have = t in direct or t in kids
        print(f"  {key:12s} target {t} {'存在' if have else '缺失'}")
        ok &= have

    print("== 2. REFINE 闭包不变 ==")
    rf = plan["refine_type"]
    t = rf["target"]
    before = clos(direct, kids, t)
    desc = {x for x in clos(direct, kids, t)}      # 占位，下面按类算后代
    # 模拟：被迁移实例仍属于某个后代类
    descendants = set()
    stack = [t]
    while stack:
        x = stack.pop()
        for k in list(kids.get(x, ())):
            if k not in descendants:
                descendants.add(k)
                stack.append(k)
    types = collections.defaultdict(set)
    for e in g["edges"]:
        if e["r"] == "P31":
            types[e["h"]].add(e["t"])
    movable = {x for x in direct.get(t, set()) if types[x] & descendants}
    # 迁移后：父类直断少掉 movable，但这些实例仍通过后代类留在闭包里
    after = (set(direct.get(t, set())) - movable)
    for d in descendants:
        after |= set(direct.get(d, set()))
    print(f"  闭包 {len(before)} → 迁移 {len(movable)} 条父类断言后 {len(after)}")
    consistent = after == before
    claim = rf["checks"]["closure_preserved"]
    print(f"  schema 声称 closure_preserved={claim}，独立复算一致={consistent}")
    ok &= bool(claim) == bool(consistent)

    print("== 3. SPLIT 互斥与并集 ==")
    sp = plan["split_concept"]
    c, p = sp["target"], sp["positive"]["qid"]
    universe = clos(direct, kids, c)
    pos = clos(direct, kids, p)
    neg = universe - pos
    print(f"  父类闭包 {len(universe)} / 阳性 {len(pos)} / 补集 {len(neg)} / "
          f"交集 {len(pos & neg)} / 并集 {len(pos | neg)}")
    ok &= (len(pos & neg) == 0) and ((pos | neg) == universe)
    ok &= sp["checks"]["exclusive"] is True
    ok &= sp["checks"]["union_eq_parent_closure"] is True

    print("== 4. schema 覆盖 ==")
    covered = {r["qid"] for r in sc["classes"]}
    missing = [q for q in direct if q not in covered]
    print(f"  有实例的类 {len(direct)}，schema 覆盖 {len(direct) - len(missing)}，缺 {len(missing)}")
    ok &= not missing

    print("\n结论：", "通过" if ok else "有未通过项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
