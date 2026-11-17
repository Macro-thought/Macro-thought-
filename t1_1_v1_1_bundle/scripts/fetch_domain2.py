# -*- coding: utf-8 -*-
"""对 domain_fetch 带进来的 109 个新尾实体再取 P17/P131，用于把 domain 推到 1500。"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
EP = "https://qlever.dev/api/wikidata"
UA = "kgc-repro/1.0"
WD = "http://www.wikidata.org/entity/"
P = "http://www.wikidata.org/prop/direct/"
F1 = r"D:\repro\schema_change\data\v1_1_domain_fetch.json"
V11 = r"D:\repro\schema_change\data\graph_v1_1.json"
CACHE = r"D:\repro\schema_change\data\v1_1_domain_fetch2.json"

if os.path.exists(CACHE):
    d = json.load(open(CACHE, encoding="utf-8"))
else:
    d = {"p17": {}, "p131": {}, "labels": {}, "types": {}, "done": [], "errors": []}
for k in ("p17", "p131", "labels", "types"):
    d.setdefault(k, {})
d.setdefault("done", [])
d.setdefault("errors", [])


def save():
    json.dump(d, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def qid(u):
    return u.rsplit("/", 1)[-1]


def vb(ids):
    return " ".join(f"wd:{i}" for i in ids)


def batched(seq, n=100):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def sparql(q, tag, timeout=45, retries=4):
    if tag in d["done"]:
        print("  skip", tag)
        return []
    req = urllib.request.Request(EP, data=urllib.parse.urlencode({"query": q}).encode(),
                                 headers={"Accept": "application/sparql-results+json",
                                          "User-Agent": UA})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for k in range(retries):
        try:
            time.sleep(5)
            with op.open(req, timeout=timeout) as r:
                rows = json.loads(r.read().decode("utf-8"))["results"]["bindings"]
            print(f"  {tag}: {len(rows)} rows")
            d["done"].append(tag)
            save()
            return rows
        except Exception as e:  # noqa: BLE001
            print(f"  retry {k} {tag}: {type(e).__name__} {str(e)[:80]}")
            time.sleep(15 + k * 15)
    d["errors"].append(tag)
    save()
    return []


f1 = json.load(open(F1, encoding="utf-8"))
g = json.load(open(V11, encoding="utf-8"))
idx = {e["id"] for e in g["entities"]}
new = sorted({x for k in ("p17", "p495", "p131_airport", "p131_city")
              for v in f1[k].values() for x in v} - idx)
print("new tails", len(new))

for key, tag, prop in (("p17", "p17", "P17"), ("p131", "p131", "P131")):
    if key in d["done"]:
        continue
    for bt in batched(new, 120):
        rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?c WHERE {{ VALUES ?s {{ {vb(bt)} }} ?s wdt:{prop} ?c . }}""", tag)
        for b in rows:
            d[key].setdefault(qid(b["s"]["value"]), []).append(qid(b["c"]["value"]))
    save()

new2 = sorted({x for k in ("p17", "p131") for v in d[k].values() for x in v} - idx - set(new))
print("new tails 2", len(new2), new2)
if new2 and "labels" not in d["done"]:
    for bt in batched(new2, 120):
        rows = sparql(f"""PREFIX wd: <{WD}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?l ?lang WHERE {{
  VALUES ?s {{ {vb(bt)} }}
  ?s rdfs:label ?l . BIND(lang(?l) AS ?lang)
  FILTER(?lang IN ("zh-hans","zh-cn","zh","zh-tw","en"))
}}""", "labels")
        for b in rows:
            d["labels"].setdefault(qid(b["s"]["value"]), {})[b["lang"]["value"]] = b["l"]["value"]
    save()
if new2 and "types" not in d["done"]:
    for bt in batched(new2, 120):
        rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?t ?tl ?lang WHERE {{
  VALUES ?s {{ {vb(bt)} }}
  ?s wdt:P31 ?t . ?t rdfs:label ?tl . BIND(lang(?tl) AS ?lang)
  FILTER(?lang IN ("zh-hans","zh-cn","zh","zh-tw","en"))
}}""", "types")
        for b in rows:
            d["types"].setdefault(qid(b["s"]["value"]), {}).setdefault(
                qid(b["t"]["value"]), {})[b["lang"]["value"]] = b["tl"]["value"]
    save()

print("p17 edges", sum(len(v) for v in d["p17"].values()),
      "p131 edges", sum(len(v) for v in d["p131"].values()))
print("new2", len(new2), "labels", len(d["labels"]), "types", len(d["types"]),
      "errors", d["errors"])
