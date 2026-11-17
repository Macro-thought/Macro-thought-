# -*- coding: utf-8 -*-
"""v1.1 体检：T1.1 硬指标 + 增强项 + 节点分类。"""
import json
import re
import sys
from collections import Counter, defaultdict, deque

from opencc import OpenCC

sys.stdout.reconfigure(encoding="utf-8")
T2S = OpenCC("t2s")
P = r"D:\repro\schema_change\data\graph_v1_1.json"
g = json.load(open(P, encoding="utf-8"))
ents, edges, meta = g["entities"], g["edges"], g["meta"]
idx = {e["id"]: e for e in ents}

deg = Counter()
for d in edges:
    deg[d["h"]] += 1
    deg[d["t"]] += 1
avg = sum(deg.values()) / len(ents)
med = sorted(deg.values())[len(ents) // 2]
trad = [e["label_zh"] for e in ents if T2S.convert(e["label_zh"]) != e["label_zh"]]
latin = [e["label_zh"] for e in ents if not re.search(r"[\u4e00-\u9fff]", e["label_zh"])]
p31 = sum(1 for d in edges if d["r"] == "P31")
p279 = sum(1 for d in edges if d["r"] == "P279")
p176 = sum(1 for d in edges if d["r"] == "P176")
p931 = sum(1 for d in edges if d["r"] == "P931")

print("=" * 66)
print("graph_v1_1 体检")
print("=" * 66)
print("实体", len(ents), "边", len(edges), "平均度", round(avg, 2), "中位", med, "最大", max(deg.values()))
print("domain", len(edges) - p31 - p279, "schema", p31 + p279, "P31", p31, "P279", p279)
print("P176", p176, "P931", p931)
print("孤儿", sum(1 for e in ents if deg.get(e["id"], 0) == 0))
print("悬空", sum(1 for d in edges if d["h"] not in idx or d["t"] not in idx))
print("自环", sum(1 for d in edges if d["h"] == d["t"]))
print("无 source", sum(1 for d in edges if not d.get("source")))
print("无 version", sum(1 for d in edges if not d.get("version")))
print("含汉字", sum(1 for e in ents if re.search(r"[\u4e00-\u9fff]", e["label_zh"])), "/", len(ents))
print("纯拉丁", len(latin), latin[:15])
print("繁体残留", len(trad), trad[:10])
print("aliases 实体", sum(1 for e in ents if e.get("aliases")), "/", len(ents),
      "条数", sum(len(e.get("aliases") or []) for e in ents))
print("node_kind", Counter(e.get("node_kind") for e in ents))
print("type top", Counter(e.get("type") for e in ents).most_common(12))
print("unknown/未分类", sum(1 for e in ents if e.get("type") in ("未知", "未分类")))
print("meta n_entities/n_edges", meta.get("n_entities"), meta.get("n_edges"))
print("meta domain/schema", meta.get("n_domain_edges"), meta.get("n_schema_edges"))
print("fingerprint", meta.get("idempotent_hash"))

# T1.1 判定
print("\nT1.1 判定:")
print("  实体 400-600:", 400 <= len(ents) <= 600, len(ents))
print("  边 1500-2500:", 1500 <= len(edges) <= 2500, len(edges))
print("  领域边 ≥1500:", len(edges) - p31 - p279 >= 1500, len(edges) - p31 - p279)
print("  无孤儿:", all(deg.get(e["id"], 0) > 0 for e in ents))
print("  无悬空:", all(d["h"] in idx and d["t"] in idx for d in edges))
print("  无自环:", not any(d["h"] == d["t"] for d in edges))
print("  每条边 source:", all(d.get("source") for d in edges))
print("  中文(含登记例外):", len(latin) <= 14, f"{len(ents)-len(latin)}+{len(latin)}")
