# -*- coding: utf-8 -*-
"""补 v1.1 的缺口：22 个机型 P176、21 个机场 P931、303 个实体的 aliases。

带磁盘缓存：每完成一条查询就写 v1_1_fetch.json，重跑从断点接上。
QLever 有 429，单条失败不 abort，记录到 errors，最后按已有数据重建。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
EP = "https://qlever.dev/api/wikidata"
UA = "kgc-repro/1.0 (academic reproducibility study)"
WD = "http://www.wikidata.org/entity/"
P = "http://www.wikidata.org/prop/direct/"
CACHE = r"D:\repro\schema_change\data\v1_1_fetch.json"
V11 = r"D:\repro\schema_change\data\graph_v1_1.json"
OURS = r"D:\repro\schema_change\data\graph_v1_r2.json"

if os.path.exists(CACHE):
    data = json.load(open(CACHE, encoding="utf-8"))
else:
    data = {"p176": {}, "p931": {}, "labels": {}, "types": {}, "p17": {},
            "aliases": {}, "done": [], "errors": []}
for k in ("p176", "p931", "labels", "types", "p17", "aliases"):
    data.setdefault(k, {})
data.setdefault("done", [])
data.setdefault("errors", [])


def save():
    json.dump(data, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def qid(u):
    return u.rsplit("/", 1)[-1]


def vb(ids):
    return " ".join(f"wd:{i}" for i in ids)


def batched(seq, n=100):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def sparql(q, tag, timeout=45, retries=4):
    if tag in data["done"]:
        print("  skip done", tag)
        return []
    data_req = urllib.parse.urlencode({"query": q}).encode("utf-8")
    req = urllib.request.Request(EP, data=data_req, headers={
        "Accept": "application/sparql-results+json", "User-Agent": UA})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for k in range(retries):
        try:
            time.sleep(5)
            with op.open(req, timeout=timeout) as r:
                obj = json.loads(r.read().decode("utf-8"))
            rows = obj["results"]["bindings"]
            print(f"  {tag}: {len(rows)} rows")
            data["done"].append(tag)
            save()
            return rows
        except Exception as e:  # noqa: BLE001
            print(f"  retry {k} {tag}: {type(e).__name__} {str(e)[:80]}")
            time.sleep(15 + k * 15)
    data["errors"].append(tag)
    save()
    return []


g = json.load(open(V11, encoding="utf-8"))
o = json.load(open(OURS, encoding="utf-8"))
idx = {e["id"]: e for e in g["entities"]}
o_idx = {e["id"]: e for e in o["entities"]}

t_ac = {d["t"] for d in g["edges"] if d["r"] == "P121"}
t_ap = {d["t"] for d in g["edges"] if d["r"] == "P113"}
o_p176_heads = {d["h"] for d in o["edges"] if d["rel"] == "制造商"}
o_p931_heads = {d["h"] for d in o["edges"] if d["rel"] == "服务城市"}
missing_ac = sorted(t_ac - o_p176_heads)
missing_ap = sorted(t_ap - o_p931_heads)
missing_alias = sorted(i for i in idx if not idx[i].get("aliases"))
print("缺 P176 机型", len(missing_ac), missing_ac)
print("缺 P931 机场", len(missing_ap), missing_ap)
print("缺 aliases 实体", len(missing_alias))

# 1) P176
if missing_ac and "p176" not in data["done"]:
    rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?t WHERE {{ VALUES ?s {{ {vb(missing_ac)} }} ?s wdt:P176 ?t . }}""", "p176")
    for b in rows:
        data["p176"].setdefault(qid(b["s"]["value"]), []).append(qid(b["t"]["value"]))
    save()

# 2) P931
if missing_ap and "p931" not in data["done"]:
    rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?t WHERE {{ VALUES ?s {{ {vb(missing_ap)} }} ?s wdt:P931 ?t . }}""", "p931")
    for b in rows:
        data["p931"].setdefault(qid(b["s"]["value"]), []).append(qid(b["t"]["value"]))
    save()

# 3) 新尾实体
new_tails = sorted({x for v in data["p176"].values() for x in v} |
                   {x for v in data["p931"].values() for x in v})
new_tails = [x for x in new_tails if x not in idx]
print("新尾实体", len(new_tails), new_tails)

if new_tails and "labels" not in data["done"]:
    rows = sparql(f"""PREFIX wd: <{WD}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?l ?lang WHERE {{
  VALUES ?s {{ {vb(new_tails)} }}
  ?s rdfs:label ?l . BIND(lang(?l) AS ?lang)
  FILTER(?lang IN ("zh-hans","zh-cn","zh","zh-tw","en"))
}}""", "labels")
    for b in rows:
        data["labels"].setdefault(qid(b["s"]["value"]), {})[b["lang"]["value"]] = b["l"]["value"]
    save()

if new_tails and "types" not in data["done"]:
    rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?t ?tl ?lang WHERE {{
  VALUES ?s {{ {vb(new_tails)} }}
  ?s wdt:P31 ?t . ?t rdfs:label ?tl . BIND(lang(?tl) AS ?lang)
  FILTER(?lang IN ("zh-hans","zh-cn","zh","zh-tw","en"))
}}""", "types")
    for b in rows:
        data["types"].setdefault(qid(b["s"]["value"]), {}).setdefault(
            qid(b["t"]["value"]), {})[b["lang"]["value"]] = b["tl"]["value"]
    save()

if new_tails and "p17" not in data["done"]:
    rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?c WHERE {{ VALUES ?s {{ {vb(new_tails)} }} ?s wdt:P17 ?c . }}""", "p17")
    for b in rows:
        data["p17"].setdefault(qid(b["s"]["value"]), []).append(qid(b["c"]["value"]))
    save()

# 4) 缺 aliases：3 批
for bi, bt in enumerate(batched(missing_alias, 100)):
    tag = f"alias_{bi}"
    if tag in data["done"]:
        continue
    rows = sparql(f"""PREFIX wd: <{WD}>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?s ?a ?lang WHERE {{
  VALUES ?s {{ {vb(bt)} }}
  ?s skos:altLabel ?a . BIND(lang(?a) AS ?lang)
  FILTER(?lang IN ("zh-hans","zh-cn","zh","zh-tw","en"))
}}""", tag)
    for b in rows:
        data["aliases"].setdefault(qid(b["s"]["value"]), []).append(b["a"]["value"])
    save()

print("\nDONE")
print("p176 heads", len(data["p176"]), "p931 heads", len(data["p931"]),
      "labels", len(data["labels"]), "types", len(data["types"]),
      "p17", len(data["p17"]), "aliases entities", len(data["aliases"]))
print("errors", data["errors"])
