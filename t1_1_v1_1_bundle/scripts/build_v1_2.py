# -*- coding: utf-8 -*-
"""v1.2-full：在 v1.1 上补全剩余的 P176/P931（含新增 50 个尾实体）。
注意：实体 660，超出 T1.1 的 400-600；这是 full 对照版，不是 T1.1 提交版。
"""
import hashlib
import json
import sys
from collections import Counter

from opencc import OpenCC

sys.stdout.reconfigure(encoding="utf-8")
T2S = OpenCC("t2s")
V11 = r"D:\repro\schema_change\data\graph_v1_1.json"
FETCH = r"D:\repro\schema_change\data\v1_1_fetch.json"
OURS = r"D:\repro\schema_change\data\graph_v1_r2.json"
OUT = r"D:\repro\schema_change\data\graph_v1_2_enriched.json"
STATS = r"D:\repro\schema_change\data\v1_2_stats.json"

g = json.load(open(V11, encoding="utf-8"))
f = json.load(open(FETCH, encoding="utf-8"))
o = json.load(open(OURS, encoding="utf-8"))
o_idx = {e["id"]: e for e in o["entities"]}
idx = {e["id"]: e for e in g["entities"]}
edge_keys = {(d["h"], d["r"], d["t"]) for d in g["edges"]}


def pick_zh(labs):
    for lg in ("zh-hans", "zh-cn", "zh", "zh-tw"):
        if lg in labs:
            return T2S.convert(labs[lg]), lg
    return None, None


def pick_type(qid, kind):
    tl = f.get("types", {}).get(qid, {})
    keys = ("航空", "飞机", "制造") if kind == "P176" else ("城市", "市", "都市", "首都")
    for tid, labs in tl.items():
        lab, _ = pick_zh(labs)
        if lab and any(k in lab for k in keys):
            return tid, lab
    for tid, labs in tl.items():
        lab, _ = pick_zh(labs)
        if lab:
            return tid, lab
    return None, ("航空制造商" if kind == "P176" else "城市")


new_entities = {}
skipped = []
for rel, key, kind in (("P176", "p176", "P176"), ("P931", "p931", "P931")):
    for h, ts in f.get(key, {}).items():
        for t in ts:
            if t in idx or t in new_entities:
                continue
            labs = f.get("labels", {}).get(t, {})
            nm, lg = pick_zh(labs)
            if not nm:
                skipped.append((rel, h, t))
                continue
            tid, tlab = pick_type(t, kind)
            new_entities[t] = {
                "id": t, "label_zh": nm, "lang_source": lg,
                "label_en": labs.get("en"),
                "type": tlab, "type_id": tid,
                "type_all": [{"id": tid, "label": tlab}] if tid else [{"id": None, "label": tlab}],
                "inception": None, "is_seed": False, "countries": [],
                "aliases": list(dict.fromkeys((o_idx.get(t, {}).get("aliases") or [])))[:30],
                "dissolved": None, "is_defunct": False,
                "type_qids": [tid] if tid else [],
                "country": (f.get("p17", {}).get(t) or [None])[0],
                "node_kind": "instance",
            }

# 他们的字段命名：type / type_qids / country / aliases / node_kind
for t, e in list(new_entities.items()):
    e.pop("type_id", None)
    e.pop("type_all", None)
    e.pop("inception", None)
    e.pop("countries", None)
    e.pop("dissolved", None)
    e.pop("is_defunct", None)

g["entities"].extend(new_entities.values())
idx = {e["id"]: e for e in g["entities"]}

added = 0
for rel, key in (("P176", "p176"), ("P931", "p931")):
    for h, ts in f.get(key, {}).items():
        for t in ts:
            if t not in idx:
                continue
            if (h, rel, t) in edge_keys:
                continue
            edge_keys.add((h, rel, t))
            g["edges"].append({"h": h, "r": rel, "t": t, "source": rel,
                               "version": "v1.2", "valid_from": None,
                               "valid_to": None, "superseded_by": None})
            added += 1

p31 = sum(1 for d in g["edges"] if d["r"] == "P31")
p279 = sum(1 for d in g["edges"] if d["r"] == "P279")
meta = g["meta"]
meta.update({
    "version": "v1.2-full",
    "variant": "full_two_hop",
    "base_version": "v1.1",
    "base_idempotent_hash": meta.get("idempotent_hash"),
    "n_entities": len(g["entities"]),
    "n_edges": len(g["edges"]),
    "n_p31": p31,
    "n_p279": p279,
    "n_schema_edges": p31 + p279,
    "n_domain_edges": len(g["edges"]) - p31 - p279,
    "n_added_p176": sum(1 for d in g["edges"] if d["r"] == "P176"),
    "n_added_p931": sum(1 for d in g["edges"] if d["r"] == "P931"),
    "n_added_entities_full": len(new_entities),
    "n_skipped_no_zh": len(skipped),
    "n_alias_entities": sum(1 for e in g["entities"] if e.get("aliases")),
    "node_kind_counts": dict(Counter(e.get("node_kind") for e in g["entities"])),
    "n_type_unknown_remaining": sum(1 for e in g["entities"] if e.get("type") in ("未知", "未分类")),
    "v1_2_notes": [
        "v1.2 = v1.1 + 全量 P176/P931（含新增 50 个尾实体）；实体 660，超 T1.1 400-600，仅作 full 对照。",
        "新增实体字段已对齐他们的 schema：id/label_zh/label_en/lang_source/type/type_qids/country/aliases/is_seed/node_kind。",
        "aliases 来自 v1_1_fetch 的 skos:altLabel + R2 按 QID 拷贝。",
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
    "n_added_p176": meta["n_added_p176"], "n_added_p931": meta["n_added_p931"],
    "n_added_entities_full": len(new_entities),
    "n_skipped_no_zh": len(skipped),
    "n_alias_entities": meta["n_alias_entities"],
    "node_kind": meta["node_kind_counts"],
    "unknown": meta["n_type_unknown_remaining"],
    "fingerprint": meta["idempotent_hash"],
    "new_entities": {k: v["label_zh"] for k, v in new_entities.items()},
}, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("entities", meta["n_entities"], "edges", meta["n_edges"],
      "domain", meta["n_domain_edges"], "schema", meta["n_schema_edges"])
print("P176", meta["n_added_p176"], "P931", meta["n_added_p931"],
      "new entities", len(new_entities), "skipped no zh", len(skipped))
print("aliases", meta["n_alias_entities"], "node_kind", meta["node_kind_counts"])
print("fingerprint", meta["idempotent_hash"])
print("new entities", [v["label_zh"] for v in new_entities.values()])
