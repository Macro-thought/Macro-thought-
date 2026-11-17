# -*- coding: utf-8 -*-
"""生成本 bundle 的 MANIFEST.json 与 CHECKSUMS.txt。"""
import hashlib
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")

VARIANTS = {
    "v1.1": "graph_v1_1.json",
    "v1.1-600": "graph_v1_1_600.json",
    "v1.2-full": "graph_v1_2_enriched.json",
    "v1.3-1500": "graph_v1_3_domain1500.json",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


files = []
for root, _dirs, names in os.walk(ROOT):
    for n in sorted(names):
        if n in ("MANIFEST.json", "CHECKSUMS.txt"):
            continue
        p = os.path.join(root, n)
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        files.append({"path": rel, "bytes": os.path.getsize(p), "sha256": sha256(p)})
files.sort(key=lambda x: x["path"])

variants = {}
for name, fn in VARIANTS.items():
    p = os.path.join(DATA, fn)
    g = json.load(open(p, encoding="utf-8"))
    m = g["meta"]
    variants[name] = {
        "file": f"data/{fn}",
        "n_entities": m.get("n_entities"),
        "n_edges": m.get("n_edges"),
        "n_domain_edges": m.get("n_domain_edges"),
        "n_schema_edges": m.get("n_schema_edges"),
        "n_p176": sum(1 for d in g["edges"] if d["r"] == "P176"),
        "n_p931": sum(1 for d in g["edges"] if d["r"] == "P931"),
        "n_alias_entities": sum(1 for e in g["entities"] if e.get("aliases")),
        "idempotent_hash": m.get("idempotent_hash"),
        "note": m.get("variant", ""),
    }

manifest = {
    "bundle": "t1_1_v1_1_bundle",
    "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    "base_graph": {
        "file": "Macro-thought/data/graph_v1.json",
        "n_entities": 590,
        "n_edges": 1857,
        "idempotent_hash": "d5935c6c56f97176",
    },
    "variants": variants,
    "files": files,
    "file_count": len(files),
    "total_bytes": sum(f["bytes"] for f in files),
}
json.dump(manifest, open(os.path.join(ROOT, "MANIFEST.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
with open(os.path.join(ROOT, "CHECKSUMS.txt"), "w", encoding="utf-8") as f:
    for x in files:
        f.write(f"{x['sha256']}  {x['path']}\n")

print("files", len(files), "bytes", manifest["total_bytes"])
for k, v in variants.items():
    print(k, v["n_entities"], v["n_edges"], v["n_domain_edges"], v["idempotent_hash"])
