# -*- coding: utf-8 -*-
"""v1.3-domain1500：补 P17/P495/P131 到 domain >=1500，并修 4 条繁简。

代价：会新增约 110 个行政区节点，实体数 >600；T1.1 的 400-600 不再满足。
600 实体版仍保留 graph_v1_1_600.json。
"""
import hashlib
import json
import sys
from collections import Counter

from opencc import OpenCC

sys.stdout.reconfigure(encoding="utf-8")
T2S = OpenCC("t2s")
V11 = r"D:\repro\schema_change\data\graph_v1_1.json"
F1 = r"D:\repro\schema_change\data\v1_1_domain_fetch.json"
F2 = r"D:\repro\schema_change\data\v1_1_domain_fetch2.json"
OURS = r"D:\repro\schema_change\data\graph_v1_r2.json"
OUT = r"D:\repro\schema_change\data\graph_v1_3_domain1500.json"
STATS = r"D:\repro\schema_change\data\v1_3_stats.json"

g = json.load(open(V11, encoding="utf-8"))
f1 = json.load(open(F1, encoding="utf-8"))
f2 = json.load(open(F2, encoding="utf-8"))
o = json.load(open(OURS, encoding="utf-8"))
o_idx = {e["id"]: e for e in o["entities"]}
idx = {e["id"]: e for e in g["entities"]}
edge_keys = {(d["h"], d["r"], d["t"]) for d in g["edges"]}

MANUAL = {"赤鱲角": "赤腊角", "赤𫚭角": "赤腊角"}


def pick_zh(labs):
    for lg in ("zh-hans", "zh-cn", "zh", "zh-tw"):
        if lg in labs:
            raw = labs[lg]
            return T2S.convert(raw), lg
    return None, None


def pick_type(qid, is_country):
    if is_country:
        return None, "国家或地区"
    tl = f1.get("types", {}).get(qid, {}) or f2.get("types", {}).get(qid, {})
    for tid, labs in tl.items():
        lab, _ = pick_zh(labs)
        if lab and any(k in lab for k in ("市", "城市", "都道府县", "县", "区", "行政区", "省", "州")):
            return tid, lab
    for tid, labs in tl.items():
        lab, _ = pick_zh(labs)
        if lab:
            return tid, lab
    return None, "行政区"


p17_tails = {t for k in ("p17",) for v in f1[k].values() for t in v} | \
            {t for v in f2.get("p17", {}).values() for t in v}


def make_entity(qid, labels, types, p17s, is_country):
    labs = labels or {}
    nm, lg = pick_zh(labs)
    if not nm:
        return None
    tid, tlab = pick_type(qid, is_country)
    return {
        "id": qid, "label_zh": nm, "label_en": labs.get("en"),
        "lang_source": lg, "type": tlab, "type_qids": [tid] if tid else [],
        "country": (p17s or [None])[0],
        "aliases": list(dict.fromkeys((o_idx.get(qid, {}).get("aliases") or [])))[:30],
        "is_seed": False, "node_kind": "country" if is_country else "instance",
    }


added = 0
new_entities = {}


def add_edge(h, rel, t, src, version="v1.3"):
    global added
    if t not in idx and t not in new_entities:
        # 从 f1/f2 的 labels/types 建实体
        labs = f1.get("labels", {}).get(t) or f2.get("labels", {}).get(t) or {}
        p17s = f1.get("p17", {}).get(t) or f2.get("p17", {}).get(t) or []
        ent = make_entity(t, labs, {}, p17s, t in p17_tails)
        if ent is None:
            return False
        new_entities[t] = ent
    if t not in idx and t not in new_entities:
        return False
    if (h, rel, t) in edge_keys or h == t:
        return False
    edge_keys.add((h, rel, t))
    g["edges"].append({"h": h, "r": rel, "t": t, "source": src,
                       "version": version, "valid_from": None,
                       "valid_to": None, "superseded_by": None})
    added += 1
    return True


# 1) f1: P17 / P495 / P131
for key, rel in (("p17", "P17"), ("p495", "P495"),
                 ("p131_airport", "P131"), ("p131_city", "P131")):
    for h, ts in f1.get(key, {}).items():
        for t in ts:
            add_edge(h, rel, t, rel)

# 2) f2: P17（新行政区的国家）
for h, ts in f2.get("p17", {}).items():
    for t in ts:
        add_edge(h, "P17", t, "P17")

# 3) 若 domain 仍 <1500，用 f2 的 P131 补到 1500
p31 = sum(1 for d in g["edges"] if d["r"] == "P31")
p279 = sum(1 for d in g["edges"] if d["r"] == "P279")
domain = len(g["edges"]) - p31 - p279
p131_candidates = [(h, t) for h, ts in f2.get("p131", {}).items() for t in ts]
# 优先尾实体已存在的
p131_candidates.sort(key=lambda x: 0 if x[1] in idx else 1)
for h, t in p131_candidates:
    if domain >= 1500:
        break
    if add_edge(h, "P131", t, "P131"):
        domain += 1

# 4) 修繁简：全部实体 label + aliases
n_fixed = 0
for e in g["entities"] + list(new_entities.values()):
    old = e["label_zh"]
    new = T2S.convert(old)
    new = MANUAL.get(new, new)
    if new != old:
        n_fixed += 1
        e["label_zh"] = new
    als = []
    for a in e.get("aliases") or []:
        a = T2S.convert(a)
        if a and a not in als:
            als.append(a)
    e["aliases"] = als[:30]

# 5) 新实体并入 + meta
g["entities"].extend(new_entities.values())
idx = {e["id"]: e for e in g["entities"]}
p31 = sum(1 for d in g["edges"] if d["r"] == "P31")
p279 = sum(1 for d in g["edges"] if d["r"] == "P279")
meta = g["meta"]
meta.update({
    "version": "v1.3-domain1500",
    "variant": "domain_1500",
    "base_version": "v1.1",
    "base_idempotent_hash": meta.get("idempotent_hash"),
    "n_entities": len(g["entities"]),
    "n_edges": len(g["edges"]),
    "n_p31": p31,
    "n_p279": p279,
    "n_schema_edges": p31 + p279,
    "n_domain_edges": len(g["edges"]) - p31 - p279,
    "n_added_domain_edges": added,
    "n_new_admin_entities": len(new_entities),
    "n_labels_fixed": n_fixed,
    "n_alias_entities": sum(1 for e in g["entities"] if e.get("aliases")),
    "node_kind_counts": dict(Counter(e.get("node_kind") for e in g["entities"])),
    "v1_3_notes": [
        "domain 补到 >=1500：P17/P495/P131 + 新行政区的 P17。",
        "新增约 110 个行政区节点，实体数 >600；T1.1 的 400-600 不再满足。",
        "4 条繁简已修：仁川国际机场/内飞地/大园区/赤腊角。",
        "600 实体版仍见 graph_v1_1_600.json（domain 1095，未到 1500）。",
    ],
})
ids = sorted(e["id"] for e in g["entities"])
sig = "|".join(ids) + "#" + "|".join(
    f"{d['h']}>{d['r']}>{d['t']}" for d in sorted(g["edges"], key=lambda x: (x["h"], x["r"], x["t"])))
meta["idempotent_hash"] = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]
json.dump(g, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({
    "n_entities": meta["n_entities"], "n_edges": meta["n_edges"],
    "n_domain_edges": meta["n_domain_edges"], "n_schema_edges": meta["n_schema_edges"],
    "n_added_domain_edges": added, "n_new_admin_entities": len(new_entities),
    "n_labels_fixed": n_fixed, "n_alias_entities": meta["n_alias_entities"],
    "node_kind": meta["node_kind_counts"],
    "fingerprint": meta["idempotent_hash"],
    "new_entities": {k: v["label_zh"] for k, v in new_entities.items()},
}, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("entities", meta["n_entities"], "edges", meta["n_edges"],
      "domain", meta["n_domain_edges"], "schema", meta["n_schema_edges"])
print("added", added, "new admin", len(new_entities), "labels fixed", n_fixed)
print("node_kind", meta["node_kind_counts"], "fingerprint", meta["idempotent_hash"])
