# -*- coding: utf-8 -*-
"""把 v1_1_fetch 的别名与「尾实体已存在」的二跳边合并进 v1.1；不新增实体。"""
import hashlib
import json
import sys
from collections import Counter

from opencc import OpenCC

sys.stdout.reconfigure(encoding="utf-8")
T2S = OpenCC("t2s")
P = r"D:\repro\schema_change\data\graph_v1_1.json"
F = r"D:\repro\schema_change\data\v1_1_fetch.json"
STATS = r"D:\repro\schema_change\data\v1_1_stats.json"

g = json.load(open(P, encoding="utf-8"))
f = json.load(open(F, encoding="utf-8"))
idx = {e["id"]: e for e in g["entities"]}
edge_keys = {(d["h"], d["r"], d["t"]) for d in g["edges"]}

# 1) 别名合并
n_fetch_alias = 0
for e in g["entities"]:
    src = f.get("aliases", {}).get(e["id"], [])
    if not src:
        continue
    cur = list(e.get("aliases") or [])
    for a in src:
        a = T2S.convert(a)
        if a and a != e.get("label_zh") and a != e.get("label_en") and a not in cur:
            cur.append(a)
    e["aliases"] = cur[:30]
    n_fetch_alias += 1

# 2) 只吸收尾实体已存在的二跳边
merged = 0
deferred = 0
for rel, key in (("P176", "p176"), ("P931", "p931")):
    for h, ts in f.get(key, {}).items():
        for t in ts:
            if t not in idx:
                deferred += 1
                continue
            if (h, rel, t) in edge_keys:
                continue
            edge_keys.add((h, rel, t))
            g["edges"].append({"h": h, "r": rel, "t": t, "source": rel,
                               "version": "v1.1", "valid_from": None,
                               "valid_to": None, "superseded_by": None})
            merged += 1

p31 = sum(1 for d in g["edges"] if d["r"] == "P31")
p279 = sum(1 for d in g["edges"] if d["r"] == "P279")
meta = g["meta"]
meta.update({
    "n_entities": len(g["entities"]),
    "n_edges": len(g["edges"]),
    "n_p31": p31,
    "n_p279": p279,
    "n_schema_edges": p31 + p279,
    "n_domain_edges": len(g["edges"]) - p31 - p279,
    "n_alias_entities": sum(1 for e in g["entities"] if e.get("aliases")),
    "n_fetched_alias_entities": n_fetch_alias,
    "n_merged_existing_tail_edges": merged,
    "n_deferred_new_tails": deferred,
    "v1_1_fetch_notes": [
        "aliases 来自 v1_1_fetch 的 skos:altLabel；已过 t2s。",
        "二跳只吸收尾实体已存在的 %d 条；另有 %d 条需要新增 50 个实体，见 graph_v1_2_enriched.json。" % (merged, deferred),
    ],
})
ids = sorted(e["id"] for e in g["entities"])
sig = "|".join(ids) + "#" + "|".join(
    f"{d['h']}>{d['r']}>{d['t']}" for d in sorted(g["edges"], key=lambda x: (x["h"], x["r"], x["t"])))
meta["idempotent_hash"] = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]
json.dump(g, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({
    "n_entities": meta["n_entities"], "n_edges": meta["n_edges"],
    "n_domain_edges": meta["n_domain_edges"], "n_schema_edges": meta["n_schema_edges"],
    "n_added_p176": sum(1 for d in g["edges"] if d["r"] == "P176"),
    "n_added_p931": sum(1 for d in g["edges"] if d["r"] == "P931"),
    "n_added_entities": 20, "n_alias_entities": meta["n_alias_entities"],
    "node_kind": dict(Counter(e.get("node_kind") for e in g["entities"])),
    "unknown_remaining": sum(1 for e in g["entities"] if e.get("type") in ("未知", "未分类")),
    "idempotent_hash": meta["idempotent_hash"],
    "new_entities": json.load(open(STATS, encoding="utf-8")).get("new_entities", {}),
    "n_fetched_alias_entities": n_fetch_alias,
    "n_merged_existing_tail_edges": merged,
    "n_deferred_new_tails": deferred,
}, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("entities", meta["n_entities"], "edges", meta["n_edges"],
      "domain", meta["n_domain_edges"], "schema", meta["n_schema_edges"])
print("alias entities", meta["n_alias_entities"], "fetched alias", n_fetch_alias)
print("merged existing-tail edges", merged, "deferred new tails", deferred)
print("fingerprint", meta["idempotent_hash"])
