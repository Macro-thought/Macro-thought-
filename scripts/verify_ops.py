#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.3 独立校验（G2 闸门）
========================
**不 import ops/apply_ops.py 的任何东西**，用自己的实现重算一遍，与产物对账。
校验脚本与被校验代码共享实现，等于自己给自己打分——这是 T1.1 就定下的规矩。

四项检查：
  1. 结构：无悬空边、无孤儿、每条边有 id/why/version、version 与文件名一致
  2. 守恒：当前边 + 退休边 ⊇ v1 的边（重定向的按 why 追，不许凭空消失）
  3. 各算子的形式条件（闭包不变 / 互斥并集 / 条件成立 / 去重）
  4. 确定性：五个产物在同一输入下重复生成指纹一致（调用方传入 manifest 比对）

    python scripts/verify_ops.py
"""

import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

FILES = {
    "v1": DATA / "graph_v1.json",
    "v1_mb": DATA / "graph_v1_mb.json",
    "v2_refine": DATA / "graph_v2_refine.json",
    "v2_restrict": DATA / "graph_v2_restrict.json",
    "v2_merge": DATA / "graph_v2_merge.json",
    "v2_split": DATA / "graph_v2_split.json",
    "v2_all": DATA / "graph_v2_all.json",
}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def idx(doc):
    """自己的索引实现：直断、父子、国家。"""
    direct = collections.defaultdict(set)
    kids = collections.defaultdict(set)
    country = {e["id"]: e.get("country") for e in doc["entities"]}
    for e in doc["edges"]:
        if e["r"] == "P31":
            direct[e["t"]].add(e["h"])
        elif e["r"] == "P279":
            kids[e["t"]].add(e["h"])
    return direct, kids, country


def closure(direct, kids, c):
    seen, stack, out = set(), [c], set(direct.get(c, ()))
    while stack:
        x = stack.pop()
        for k in kids.get(x, ()):
            if k not in seen:
                seen.add(k)
                stack.append(k)
                out |= set(direct.get(k, ()))
    return out


def fp(doc):
    h = hashlib.sha1()
    for e in sorted(doc["entities"], key=lambda x: x["id"]):
        h.update(("E|" + e["id"] + "|" + (e.get("label_zh") or "")).encode())
    for e in sorted(doc["edges"], key=lambda x: (x["h"], x["r"], x["t"])):
        h.update(("R|" + e["h"] + "|" + e["r"] + "|" + e["t"]).encode())
    return h.hexdigest()[:16]


def structural(doc, tag):
    errs = []
    ids = {e["id"] for e in doc["entities"]}
    deg = collections.Counter()
    for e in doc["edges"]:
        if e["h"] not in ids or e["t"] not in ids:
            errs.append(f"悬空边 {e['h']}-{e['r']}-{e['t']}")
        deg[e["h"]] += 1
        deg[e["t"]] += 1
        need = ("version", "source") if tag == "v1" else ("id", "why", "version", "source")
        for k in need:
            if not e.get(k):
                errs.append(f"边缺 {k}: {e}")
    iso = [i for i in ids if deg[i] == 0]
    if iso:
        errs.append(f"孤立节点 {len(iso)} 个：{iso[:5]}")
    if doc["meta"].get("version") != tag:
        errs.append(f"version 字段 {doc['meta'].get('version')} != {tag}")
    return errs


def conservation(v1, doc):
    """v1 的三元组必须能追到：在当前边里，或在退休边里（重定向的按目的节点配对）。"""
    cur = {(e["h"], e["r"], e["t"]) for e in doc["edges"]}
    ret = {(e["h"], e["r"], e["t"]) for e in doc.get("retired_edges", [])}
    missing = []
    for e in v1["edges"]:
        t = (e["h"], e["r"], e["t"])
        if t in cur or t in ret:
            continue
        missing.append(t)
    return missing


def check_refine(v1, doc, direct, kids):
    errs = []
    c = "Q1248784"
    v1c = closure(*idx(v1)[:2], c)
    v2c = closure(direct, kids, c)
    if v1c != v2c:
        errs.append(f"闭包变了：v1 {len(v1c)} / v2 {len(v2c)}")
    # 不得再有「父+后代」双断言
    for x in list(direct.get(c, ())):
        desc = set()
        stack = [c]
        while stack:
            y = stack.pop()
            for k in kids.get(y, ()):
                if k not in desc:
                    desc.add(k)
                    stack.append(k)
        types = {t for t, ss in direct.items() if x in ss}
        if types & desc:
            errs.append(f"{x} 仍同时断言父类与后代")
    return errs


def check_split(v1, doc, direct, kids):
    errs = []
    c, p = "Q46970", "Q1057026"
    comp = [e["id"] for e in doc["entities"] if e.get("synthetic") and "split" in str(e.get("synthetic_note", "")).lower()]
    synth = [e["id"] for e in doc["entities"] if e["id"].startswith("Q_synth_")]
    if not synth:
        return ["补集类不存在"]
    cq = synth[0]
    if (cq, "P279", c) not in {(e["h"], e["r"], e["t"]) for e in doc["edges"]}:
        errs.append("补集类没有 P279 → 父类")
    v1u = closure(*idx(v1)[:2], c)
    pos = closure(direct, kids, p)
    neg = set(direct.get(cq, ()))
    if pos & neg:
        errs.append(f"两分支不互斥：{len(pos & neg)}")
    if (pos | neg) != v1u:
        errs.append(f"并集 != 父类闭包：{len(pos | neg)} vs {len(v1u)}")
    if direct.get(c):
        errs.append(f"父类仍有直断实例 {len(direct[c])}")
    return errs


def check_restrict(v1, doc, direct, kids, country):
    errs = []
    r = "P113"
    bad = [e for e in doc["edges"] if e["r"] == r and country.get(e["t"]) != "Q148"]
    if bad:
        errs.append(f"仍有 {len(bad)} 条 {r} 边不满足条件")
    n1 = sum(1 for e in v1["edges"] if e["r"] == r)
    n2 = sum(1 for e in doc["edges"] if e["r"] == r)
    if n2 >= n1:
        errs.append(f"{r} 边未减少：{n1} → {n2}")
    # 只对「因收窄而退休」的边要求 valid_to；因合并重定向退休的边不涉及时间
    retired = [e for e in doc.get("retired_edges", [])
               if e["r"] == r and str(e.get("why", "")).startswith("关系收窄")]
    if any(not e.get("valid_to") for e in retired):
        errs.append("退休边缺 valid_to")
    return errs


def check_merge(v1, doc, direct, kids):
    errs = []
    left = [e["id"] for e in doc["entities"] if e["id"].endswith("-dup")]
    if left:
        errs.append(f"仍有 dup 节点 {len(left)}")
    n1 = len(v1["edges"])
    n2 = len(doc["edges"])
    if n2 != n1:
        errs.append(f"边数不守恒：v1 {n1} / v2 {n2}")
    n_e1 = len(v1["entities"])
    if len(doc["entities"]) != n_e1:
        errs.append(f"实体数不守恒：v1 {n_e1} / v2 {len(doc['entities'])}")
    return errs


def main():
    docs = {k: load(p) for k, p in FILES.items() if p.exists()}
    v1 = docs["v1"]
    ok = True
    print("== 1. 结构 ==")
    for k, d in docs.items():
        errs = structural(d, k)
        print(f"  {k:11s} 实体 {len(d['entities']):4d} 边 {len(d['edges']):5d} "
              f"退休 {len(d.get('retired_edges', [])):4d} 指纹 {fp(d)} "
              f"{'OK' if not errs else 'FAIL'}")
        for e in errs[:3]:
            print("     !", e)
        ok &= not errs

    print("== 2. 守恒（v1 的边可追）==")
    for k, d in docs.items():
        if k in ("v1", "v1_mb"):
            continue
        miss = conservation(v1, d)
        print(f"  {k:11s} 丢失 {len(miss)} 条 {miss[:2] if miss else ''}")
        ok &= not miss

    print("== 3. 各算子形式条件 ==")
    for k in ("v2_refine", "v2_split", "v2_restrict", "v2_merge", "v2_all"):
        if k not in docs:
            continue
        d = docs[k]
        direct, kids, country = idx(d)
        errs = []
        if k in ("v2_refine", "v2_all"):
            errs += check_refine(v1, d, direct, kids)
        if k in ("v2_split", "v2_all"):
            errs += check_split(v1, d, direct, kids)
        if k in ("v2_restrict", "v2_all"):
            errs += check_restrict(v1, d, direct, kids, country)
        if k == "v2_merge":
            errs += check_merge(v1, d, direct, kids)
        if k == "v2_all":
            left = [e["id"] for e in d["entities"] if e["id"].endswith("-dup")]
            if left:
                errs.append(f"仍有 dup 节点 {len(left)}")
        print(f"  {k:11s} {'OK' if not errs else 'FAIL ' + '; '.join(errs[:3])}")
        ok &= not errs

    print("== 4. 确定性（与 meta 记录比对）==")
    for k, d in docs.items():
        if k == "v1":
            continue
        rec = d["meta"].get("idempotent_hash")
        cur = fp(d)
        print(f"  {k:11s} meta {rec} / 重算 {cur} {'一致' if rec == cur else '不一致'}")
        ok &= rec == cur

    print("\n结论：", "全部通过" if ok else "有未通过项（见上）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
