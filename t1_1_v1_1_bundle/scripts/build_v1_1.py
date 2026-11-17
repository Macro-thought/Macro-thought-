# -*- coding: utf-8 -*-
"""在组员 graph_v1.json 上做 v1.1 增强（不改原图）：

1. 拆 T1.1 边数：total / domain / schema(P31,P279) 写入 meta。
2. 补二跳：P176（机型→制造商）、P931（机场→城市），从我们的 R2 图按 QID 对齐。
3. 补 aliases：从 R2 的 skos:altLabel 结果拷贝（按 QID 对齐），并补 label_en。
4. 类型/节点单列：把 134 个「未知」按边角色分成 country / class / other；新增 node_kind。
"""
import copy
import hashlib
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
THEIRS = r"C:\Users\duan\Desktop\T1.1\Macro-thought-\data\graph_v1.json"
OURS = r"D:\repro\schema_change\data\graph_v1_r2.json"
OURS_SCHEMA = r"D:\repro\schema_change\data\schema_r2.json"
OUT = r"D:\repro\schema_change\data\graph_v1_1.json"
OUT_STATS = r"D:\repro\schema_change\data\v1_1_stats.json"

t = json.load(open(THEIRS, encoding="utf-8"))
o = json.load(open(OURS, encoding="utf-8"))
s = json.load(open(OURS_SCHEMA, encoding="utf-8"))
t_idx = {e["id"]: e for e in t["entities"]}
o_idx = {e["id"]: e for e in o["entities"]}
o_type = {e["id"]: e["main_type"] for e in s["entities"]}
o_country = {}
for d in o["edges"]:
    if d["rel"] == "所属国家或地区":
        o_country.setdefault(d["h"], d["t"])

entities = copy.deepcopy(t["entities"])
edges = copy.deepcopy(t["edges"])
edge_keys = {(d["h"], d["r"], d["t"]) for d in edges}

t_aircraft = {d["t"] for d in edges if d["r"] == "P121"}
t_airports = {d["t"] for d in edges if d["r"] == "P113"}

# ---- 1. 二跳边：从 R2 按 QID 对齐 ----
p176_raw = [(d["h"], d["t"]) for d in o["edges"]
            if d["rel"] == "制造商" and d["h"] in t_aircraft]
p931_raw = [(d["h"], d["t"]) for d in o["edges"]
            if d["rel"] == "服务城市" and d["h"] in t_airports]
p176 = sorted({(h, t) for h, t in p176_raw if h != t})
p931 = sorted({(h, t) for h, t in p931_raw if h != t})
new_tails = {t2 for _, t2 in p176} | {t2 for _, t2 in p931}
new_tails -= set(t_idx)

new_entities = {}
for qid in sorted(new_tails):
    oe = o_idx[qid]
    if any(t2 == qid for _, t2 in p176):
        typ = "航空制造商"
    elif any(t2 == qid for _, t2 in p931):
        typ = "城市"
    else:
        typ = o_type.get(qid) or oe.get("type_label") or "未分类"
    new_entities[qid] = {
        "id": qid,
        "label_zh": oe["label_zh"],
        "label_en": oe.get("label_en"),
        "lang_source": oe.get("label_lang") or "zh",
        "type": typ,
        "type_qids": ([oe["type_id"]] if oe.get("type_id") else []),
        "country": o_country.get(qid),
        "aliases": list(dict.fromkeys(oe.get("aliases") or []))[:30],
        "is_seed": False,
        "node_kind": "instance",
    }
entities.extend(new_entities.values())

added_p176 = added_p931 = 0
for h, t2 in p176:
    if (h, "P176", t2) in edge_keys:
        continue
    edge_keys.add((h, "P176", t2))
    edges.append({"h": h, "r": "P176", "t": t2, "source": "P176",
                  "version": "v1.1", "valid_from": None, "valid_to": None,
                  "superseded_by": None})
    added_p176 += 1
for h, t2 in p931:
    if (h, "P931", t2) in edge_keys:
        continue
    edge_keys.add((h, "P931", t2))
    edges.append({"h": h, "r": "P931", "t": t2, "source": "P931",
                  "version": "v1.1", "valid_from": None, "valid_to": None,
                  "superseded_by": None})
    added_p931 += 1

# ---- 2. aliases / label_en ----
n_alias = 0
for e in entities:
    src = o_idx.get(e["id"], {}).get("aliases") or []
    if src:
        e["aliases"] = list(dict.fromkeys(src))[:30]
    if not e.get("label_en"):
        e["label_en"] = o_idx.get(e["id"], {}).get("label_en")
    if e.get("aliases"):
        n_alias += 1

# ---- 3. 未知节点按边角色单列 ----
p17_tails = {d["t"] for d in edges if d["r"] == "P17"}
p31_tails = {d["t"] for d in edges if d["r"] == "P31"}
p279_nodes = {d["h"] for d in edges if d["r"] == "P279"} | \
             {d["t"] for d in edges if d["r"] == "P279"}

kind = Counter()
for e in entities:
    if e["id"] in p17_tails:
        e["node_kind"] = "country"
    elif e["id"] in p31_tails or e["id"] in p279_nodes:
        e["node_kind"] = "class"
    elif e["id"] in new_entities:
        e["node_kind"] = "instance"
    else:
        e["node_kind"] = "instance"
    if e.get("type") in ("未知", "未标注", None, ""):
        if e["node_kind"] == "country":
            e["type"] = "国家或地区"
            e["country"] = e["country"] or e["id"]
        elif e["node_kind"] == "class":
            e["type"] = "类"
        else:
            e["type"] = "未分类"
    kind[e["node_kind"]] += 1

# ---- 4. meta：T1.1 边数拆分 + 指纹 ----
p31 = sum(1 for d in edges if d["r"] == "P31")
p279 = sum(1 for d in edges if d["r"] == "P279")
meta = dict(t["meta"])
meta.update({
    "version": "v1.1",
    "base_version": "v1",
    "base_idempotent_hash": t["meta"].get("idempotent_hash"),
    "built_at": "2026-11-17T19:45:00",
    "n_entities": len(entities),
    "n_edges": len(edges),
    "n_p31": p31,
    "n_p279": p279,
    "n_schema_edges": p31 + p279,
    "n_domain_edges": len(edges) - p31 - p279,
    "n_added_p176": added_p176,
    "n_added_p931": added_p931,
    "n_added_entities": len(new_entities),
    "n_alias_entities": n_alias,
    "node_kind_counts": dict(kind),
    "n_type_unknown_remaining": sum(1 for e in entities if e["type"] in ("未知", "未分类")),
    "v1_1_notes": [
        "P176/P931 从 graph_v1_r2 按 QID 对齐补入；未重抓，两个快照相差 1 天。",
        "aliases 从 R2 的 skos:altLabel 结果按 QID 拷贝；未覆盖的实体仍为空。",
        "node_kind 按边角色判定（P17 尾=country，P31/P279=class，其余=instance），不是 Wikidata P31。",
        "T1.1 边数：domain=%d，schema=%d，total=%d。" % (len(edges) - p31 - p279, p31 + p279, len(edges)),
    ],
})
ids = sorted(e["id"] for e in entities)
sig = "|".join(ids) + "#" + "|".join(
    f"{d['h']}>{d['r']}>{d['t']}" for d in sorted(edges, key=lambda x: (x["h"], x["r"], x["t"])))
meta["idempotent_hash"] = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]

out = {"meta": meta, "entities": entities, "edges": edges}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({
    "n_entities": len(entities), "n_edges": len(edges),
    "n_domain_edges": meta["n_domain_edges"], "n_schema_edges": meta["n_schema_edges"],
    "n_added_p176": added_p176, "n_added_p931": added_p931,
    "n_added_entities": len(new_entities), "n_alias_entities": n_alias,
    "node_kind": dict(kind), "unknown_remaining": meta["n_type_unknown_remaining"],
    "idempotent_hash": meta["idempotent_hash"],
    "new_entities": {k: v["label_zh"] for k, v in new_entities.items()},
}, open(OUT_STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("实体", len(entities), "边", len(edges))
print("domain", meta["n_domain_edges"], "schema", meta["n_schema_edges"],
      "P31", p31, "P279", p279)
print("added P176", added_p176, "P931", added_p931, "new entities", len(new_entities))
print("aliases", n_alias, "/", len(entities), "node_kind", dict(kind),
      "unknown remaining", meta["n_type_unknown_remaining"])
print("fingerprint", meta["idempotent_hash"])
print("new entities:", [v["label_zh"] for v in new_entities.values()])
