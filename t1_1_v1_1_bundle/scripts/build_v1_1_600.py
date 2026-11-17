# -*- coding: utf-8 -*-
"""从 graph_v1_1 做一个严格 600 实体的变体：贪心删 10 个噪声实例，且不制造孤儿。"""
import hashlib
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
SRC = r"D:\repro\schema_change\data\graph_v1_1.json"
OUT = r"D:\repro\schema_change\data\graph_v1_1_600.json"
STATS = r"D:\repro\schema_change\data\v1_1_600_stats.json"

g = json.load(open(SRC, encoding="utf-8"))
ents = g["entities"]
edges = g["edges"]
new_ids = set(json.load(open(r"D:\repro\schema_change\data\v1_1_stats.json", encoding="utf-8"))["new_entities"])

NOISE = {"人类", "建筑群", "日本特别区", "日本行政区", "组织", "企业",
         "人类聚居地", "中国国有企业", "未分类", "建筑", "办公楼"}


def degree(es):
    d = Counter()
    for x in es:
        d[x["h"]] += 1
        d[x["t"]] += 1
    return d


deg0 = degree(edges)
cand = [e for e in ents
        if e.get("node_kind") == "instance"
        and not e.get("is_seed")
        and e["id"] not in new_ids
        and e.get("type") not in ("类", "国家或地区", "航空制造商", "城市")]
cand.sort(key=lambda e: (0 if e.get("type") in NOISE else 1, deg0.get(e["id"], 0)))

drop = set()
for e in cand:
    trial = drop | {e["id"]}
    trial_edges = [d for d in edges if d["h"] not in trial and d["t"] not in trial]
    d2 = degree(trial_edges)
    remain = [x for x in ents if x["id"] not in trial]
    if all(d2.get(x["id"], 0) > 0 for x in remain):
        drop.add(e["id"])
    if len(drop) == 10:
        break

ents2 = [e for e in ents if e["id"] not in drop]
edges2 = [d for d in edges if d["h"] not in drop and d["t"] not in drop]
idx2 = {e["id"]: e for e in ents2}
p31 = sum(1 for d in edges2 if d["r"] == "P31")
p279 = sum(1 for d in edges2 if d["r"] == "P279")
meta = dict(g["meta"])
meta.update({
    "version": "v1.1-600",
    "variant": "600_cap",
    "base_version": "v1.1",
    "base_idempotent_hash": g["meta"].get("idempotent_hash"),
    "n_entities": len(ents2),
    "n_edges": len(edges2),
    "n_p31": p31,
    "n_p279": p279,
    "n_schema_edges": p31 + p279,
    "n_domain_edges": len(edges2) - p31 - p279,
    "node_kind_counts": dict(Counter(e.get("node_kind") for e in ents2)),
    "dropped_entities": sorted(drop),
    "n_dropped_entities": len(drop),
    "n_type_unknown_remaining": sum(1 for e in ents2 if e.get("type") in ("未知", "未分类")),
    "v1_1_600_notes": [
        "贪心删 10 个低度噪声实例（人物/建筑/区/企业），每次删完检查不产生孤儿。",
        "不删类、国家、种子、二跳新实体；类节点数保持 118。",
        "总边仍 >1500；领域边仍 <1500。",
    ],
})
ids = sorted(e["id"] for e in ents2)
sig = "|".join(ids) + "#" + "|".join(
    f"{d['h']}>{d['r']}>{d['t']}" for d in sorted(edges2, key=lambda x: (x["h"], x["r"], x["t"])))
meta["idempotent_hash"] = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]
json.dump({"meta": meta, "entities": ents2, "edges": edges2},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({
    "n_entities": len(ents2), "n_edges": len(edges2),
    "n_domain_edges": meta["n_domain_edges"], "n_schema_edges": meta["n_schema_edges"],
    "n_dropped": len(drop), "dropped": sorted(drop),
    "node_kind": meta["node_kind_counts"], "unknown": meta["n_type_unknown_remaining"],
    "fingerprint": meta["idempotent_hash"],
    "dropped_labels": [idx2.get(x, {}).get("label_zh") for x in sorted(drop)],
}, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

deg = degree(edges2)
print("entities", len(ents2), "edges", len(edges2), "domain", meta["n_domain_edges"],
      "schema", meta["n_schema_edges"], "dropped", len(drop))
print("dropped", [(x, next((e['label_zh'] for e in ents if e['id'] == x), '?')) for x in sorted(drop)])
print("orphans", sum(1 for e in ents2 if deg.get(e["id"], 0) == 0),
      "dangling", sum(1 for d in edges2 if d["h"] not in idx2 or d["t"] not in idx2),
      "self", sum(1 for d in edges2 if d["h"] == d["t"]))
print("node_kind", meta["node_kind_counts"], "fingerprint", meta["idempotent_hash"])
