# -*- coding: utf-8 -*-
"""修 v1.3 的 2 条悬空边：删掉缺失头实体的边，再用已有端点的域边补回 1500。"""
import hashlib
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
P = r"D:\repro\schema_change\data\graph_v1_3_domain1500.json"
F1 = r"D:\repro\schema_change\data\v1_1_domain_fetch.json"
F2 = r"D:\repro\schema_change\data\v1_1_domain_fetch2.json"

g = json.load(open(P, encoding="utf-8"))
f1 = json.load(open(F1, encoding="utf-8"))
f2 = json.load(open(F2, encoding="utf-8"))
idx = {e["id"] for e in g["entities"]}
edges = [d for d in g["edges"] if d["h"] in idx and d["t"] in idx]
keys = {(d["h"], d["r"], d["t"]) for d in edges}
removed = len(g["edges"]) - len(edges)
print("removed dangling", removed)

p31 = sum(1 for d in edges if d["r"] == "P31")
p279 = sum(1 for d in edges if d["r"] == "P279")
domain = len(edges) - p31 - p279


def add_existing():
    global domain
    for f, pairs in ((f1, (("p17", "P17"), ("p495", "P495"),
                           ("p131_airport", "P131"), ("p131_city", "P131"))),
                     (f2, (("p17", "P17"), ("p131", "P131")))):
        for key, rel in pairs:
            for h, ts in f.get(key, {}).items():
                if h not in idx:
                    continue
                for t in ts:
                    if t not in idx or h == t:
                        continue
                    if (h, rel, t) in keys:
                        continue
                    keys.add((h, rel, t))
                    edges.append({"h": h, "r": rel, "t": t, "source": rel,
                                  "version": "v1.3", "valid_from": None,
                                  "valid_to": None, "superseded_by": None})
                    domain += 1
                    if domain >= 1500:
                        return


add_existing()
print("domain after fill", domain)
g["edges"] = edges
g["meta"].update({
    "n_edges": len(edges),
    "n_p31": p31,
    "n_p279": p279,
    "n_schema_edges": p31 + p279,
    "n_domain_edges": domain,
    "n_dangling_fixed": removed,
})
ids = sorted(e["id"] for e in g["entities"])
sig = "|".join(ids) + "#" + "|".join(
    f"{d['h']}>{d['r']}>{d['t']}" for d in sorted(edges, key=lambda x: (x["h"], x["r"], x["t"])))
g["meta"]["idempotent_hash"] = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]
json.dump(g, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("entities", len(g["entities"]), "edges", len(edges), "domain", domain,
      "fingerprint", g["meta"]["idempotent_hash"])
