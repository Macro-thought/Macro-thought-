# -*- coding: utf-8 -*-
"""把四份增强图的繁简统一（OpenCC + 赤鱲角→赤腊角），并更新指纹/stats。"""
import hashlib
import json
import sys

from opencc import OpenCC

sys.stdout.reconfigure(encoding="utf-8")
T2S = OpenCC("t2s")
MANUAL = {"赤鱲角": "赤腊角", "赤𫚭角": "赤腊角"}
FILES = [
    (r"D:\repro\schema_change\data\graph_v1_1.json",
     r"D:\repro\schema_change\data\v1_1_stats.json"),
    (r"D:\repro\schema_change\data\graph_v1_1_600.json",
     r"D:\repro\schema_change\data\v1_1_600_stats.json"),
    (r"D:\repro\schema_change\data\graph_v1_2_enriched.json",
     r"D:\repro\schema_change\data\v1_2_stats.json"),
    (r"D:\repro\schema_change\data\graph_v1_3_domain1500.json",
     r"D:\repro\schema_change\data\v1_3_stats.json"),
]

for path, stats_path in FILES:
    g = json.load(open(path, encoding="utf-8"))
    n = 0
    for e in g["entities"]:
        old = e["label_zh"]
        new = MANUAL.get(T2S.convert(old), T2S.convert(old))
        if new != old:
            e["label_zh"] = new
            n += 1
        als = []
        for a in e.get("aliases") or []:
            a = T2S.convert(a)
            if a and a not in als:
                als.append(a)
        e["aliases"] = als[:30]
    ids = sorted(e["id"] for e in g["entities"])
    sig = "|".join(ids) + "#" + "|".join(
        f"{d['h']}>{d['r']}>{d['t']}" for d in sorted(g["edges"], key=lambda x: (x["h"], x["r"], x["t"])))
    fp = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]
    g["meta"]["idempotent_hash"] = fp
    g["meta"]["n_labels_fixed_total"] = n
    json.dump(g, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        st = json.load(open(stats_path, encoding="utf-8"))
        for k in ("idempotent_hash", "fingerprint"):
            if k in st:
                st[k] = fp
        json.dump(st, open(stats_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    print(path.rsplit("\\", 1)[-1], "labels fixed", n, "fingerprint", fp)
