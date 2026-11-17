# -*- coding: utf-8 -*-
"""为补到 domain 1500 探数：P17（缺国家的实体）、P495（机型原产国）、P131（机场/城市所在地）。"""
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
CACHE = r"D:\repro\schema_change\data\v1_1_domain_fetch.json"
V11 = r"D:\repro\schema_change\data\graph_v1_1.json"

if os.path.exists(CACHE):
    data = json.load(open(CACHE, encoding="utf-8"))
else:
    data = {"p17": {}, "p495": {}, "p131_airport": {}, "p131_city": {},
            "labels": {}, "types": {}, "done": [], "errors": []}
for k in ("p17", "p495", "p131_airport", "p131_city", "labels", "types"):
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
ents = g["entities"]
idx = {e["id"]: e for e in ents}
has_p17 = {d["h"] for d in g["edges"] if d["r"] == "P17"}
missing_p17 = sorted(i for i in idx if i not in has_p17)
aircraft = sorted({d["t"] for d in g["edges"] if d["r"] == "P121"})
airports = sorted({d["t"] for d in g["edges"] if d["r"] == "P113"})
CITY = ("城市", "市", "首都", "区", "都", "县", "行政区", "人类聚居地",
        "国家中心城市", "国际会议观光都市", "大城市")
cities = sorted(i for i, e in idx.items()
                if any(k in (e.get("type") or "") for k in CITY)
                and i not in aircraft and i not in airports)
print("missing P17", len(missing_p17), "aircraft", len(aircraft),
      "airports", len(airports), "cities", len(cities))

if missing_p17 and "p17" not in data["done"]:
    for bt in batched(missing_p17, 120):
        rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?c WHERE {{ VALUES ?s {{ {vb(bt)} }} ?s wdt:P17 ?c . }}""", "p17")
        for b in rows:
            data["p17"].setdefault(qid(b["s"]["value"]), []).append(qid(b["c"]["value"]))
    save()

if aircraft and "p495" not in data["done"]:
    rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?c WHERE {{ VALUES ?s {{ {vb(aircraft)} }} ?s wdt:P495 ?c . }}""", "p495")
    for b in rows:
        data["p495"].setdefault(qid(b["s"]["value"]), []).append(qid(b["c"]["value"]))
    save()

if airports and "p131_airport" not in data["done"]:
    rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?c WHERE {{ VALUES ?s {{ {vb(airports)} }} ?s wdt:P131 ?c . }}""", "p131_airport")
    for b in rows:
        data["p131_airport"].setdefault(qid(b["s"]["value"]), []).append(qid(b["c"]["value"]))
    save()

if cities and "p131_city" not in data["done"]:
    for bt in batched(cities, 120):
        rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
SELECT ?s ?c WHERE {{ VALUES ?s {{ {vb(bt)} }} ?s wdt:P131 ?c . }}""", "p131_city")
        for b in rows:
            data["p131_city"].setdefault(qid(b["s"]["value"]), []).append(qid(b["c"]["value"]))
    save()

new_tails = sorted({x for k in ("p17", "p495", "p131_airport", "p131_city")
                    for v in data[k].values() for x in v} - set(idx))
print("new tails", len(new_tails), new_tails)
if new_tails and "labels" not in data["done"]:
    for bt in batched(new_tails, 120):
        rows = sparql(f"""PREFIX wd: <{WD}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?l ?lang WHERE {{
  VALUES ?s {{ {vb(bt)} }}
  ?s rdfs:label ?l . BIND(lang(?l) AS ?lang)
  FILTER(?lang IN ("zh-hans","zh-cn","zh","zh-tw","en"))
}}""", "labels")
        for b in rows:
            data["labels"].setdefault(qid(b["s"]["value"]), {})[b["lang"]["value"]] = b["l"]["value"]
    save()

if new_tails and "types" not in data["done"]:
    for bt in batched(new_tails, 120):
        rows = sparql(f"""PREFIX wdt: <{P}>
PREFIX wd: <{WD}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?t ?tl ?lang WHERE {{
  VALUES ?s {{ {vb(bt)} }}
  ?s wdt:P31 ?t . ?t rdfs:label ?tl . BIND(lang(?tl) AS ?lang)
  FILTER(?lang IN ("zh-hans","zh-cn","zh","zh-tw","en"))
}}""", "types")
        for b in rows:
            data["types"].setdefault(qid(b["s"]["value"]), {}).setdefault(
                qid(b["t"]["value"]), {})[b["lang"]["value"]] = b["tl"]["value"]
    save()

print("\nDONE")
for k in ("p17", "p495", "p131_airport", "p131_city"):
    print(k, "heads", len(data[k]), "edges", sum(len(v) for v in data[k].values()))
print("new tails", len(new_tails), "labels", len(data["labels"]), "types", len(data["types"]))
print("errors", data["errors"])
