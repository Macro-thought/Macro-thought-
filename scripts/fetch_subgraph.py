#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.1 取航空子图
================
从 QLever 的 Wikidata 全量镜像取出「中国 + 港澳台 + 日韩」航空公司及其一跳邻居，
产出受控中文子图 data/graph_v1.json，供 T1.3 的 schema 算子使用。

用法：
    python scripts/fetch_subgraph.py                # 全量
    python scripts/fetch_subgraph.py --limit 20     # 冒烟测试，只取前 20 个种子
    python scripts/fetch_subgraph.py --no-convert   # 不做繁简转换（只统计可疑条数）

两个必须知道的坑：
1. 本机 http(s)_proxy 指向一个连不通的代理，所有请求必须绕开，否则表现为
   「DNS 正常但全部超时」。本脚本用 urllib 的 ProxyHandler({}) 显式绕过，
   不依赖环境变量，也不需要 curl 的 --noproxy。
2. QLever 不支持 SERVICE wikibase:label，标签一律用 rdfs:label + 语言过滤。

第三个坑（2026-11-16 实测新增）：
3. qlever.dev 对出口 IP 有 nginx 层 limit_req，连续查询会返回 429，且恢复时间不确定
   （等 75s 仍不恢复）。所以本脚本把每条查询的结果按 query 的 sha1 缓存到
   data/cache/，重跑只补缺的那几条；遇到 429 按 45/90/180… 秒退避，最多 6 轮。
   中途被杀掉也没关系，再跑一次会从缓存接上。

验收（六项，脚本末尾自动检查，任一项不过返回非零退出码）：
    实体 400-600 / 边 1500-2500 / 中文名 100% / 孤儿 0 / 每条边有 source / 繁简统一有记录
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- 常量

ENDPOINT = "https://qlever.dev/api/wikidata"
USER_AGENT = "schema-change-t11/0.1 (undergraduate research project)"

PREFIX = (
    "PREFIX wd: <http://www.wikidata.org/entity/>\n"
    "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
)

AIRLINE_CLASS = "Q46970"                     # 航空公司
SEED_COUNTRIES = ["Q148", "Q8646", "Q14773", "Q865", "Q17", "Q884"]
#                 中国   香港     澳门      台湾地区  日本   韩国

# 一跳扩展的关系白名单（属性号）
WHITELIST = ["P121", "P113", "P176", "P749", "P127", "P159"]
#           运营于 航空枢纽 制造商 母公司 所属集团 总部所在地

ZH_ORDER = ["zh-hans", "zh-cn", "zh", "zh-hant", "zh-tw"]
NEEDS_CONVERT = {"zh", "zh-hant", "zh-tw"}
BATCH = 200          # 批次尽量大，减少请求数——QLever 对出口 IP 限流很紧

ROOT = Path(__file__).resolve().parent.parent   # 仓库根目录
DEFAULT_OUT = ROOT / "data" / "graph_v1.json"
LOG_PATH = ROOT / "data" / "fetch_log.json"
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / "cache"

LOG = []          # 每条查询的记录，最后落 fetch_log.json

# 限流退避：QLever 的 429 是 nginx 层的 limit_req，实测大约 20–60 秒才放一次。
# 退避从 20s 起翻倍、上限 300s——翻得太狠会在配额已恢复时白睡十几分钟。
BACKOFF_BASE = 20
BACKOFF_CAP = 300
MAX_ATTEMPTS = 10


# ---------------------------------------------------------------- 查询层

def _cache_path(query):
    # 端点也要进 key：换源后不能复用旧源的结果，否则数据卡上的来源就是假的
    key = hashlib.sha1((ENDPOINT + "\n" + query).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def sparql(query, tag, timeout=90):
    """
    取一条 SPARQL 的结果。三层保护：
    1. 磁盘缓存 —— 同一个查询只发一次，重跑/续跑不消耗配额；
    2. 走 ProxyHandler({}) 绕开本机那个连不通的代理；
    3. 429 时按 45/90/180… 秒退避重试，最多 6 轮。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(query)
    if cache.exists():
        try:
            bindings = json.loads(cache.read_text(encoding="utf-8"))
            if bindings:
                print(f"    · {tag} 命中缓存（{len(bindings)} 行）")
                LOG.append({"tag": tag, "rows": len(bindings), "ms": 0, "cached": True, "query": query})
                return bindings, 0
        except Exception:                                          # noqa: BLE001
            pass                                                   # 缓存坏了就重查

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = ENDPOINT + "?query=" + urllib.parse.quote(query)
    req = urllib.request.Request(
        url, headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT}
    )
    last = None
    for attempt in range(MAX_ATTEMPTS):
        t0 = time.time()
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = json.load(resp)
            ms = int((time.time() - t0) * 1000)
            bindings = data.get("results", {}).get("bindings", [])
            cache.write_text(json.dumps(bindings, ensure_ascii=False), encoding="utf-8")
            LOG.append({"tag": tag, "rows": len(bindings), "ms": ms, "query": query})
            return bindings, ms
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 429:
                wait = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_CAP)
                print(f"    ! {tag} 被限流（429），第 {attempt + 1}/{MAX_ATTEMPTS} 轮，等 {wait}s")
            else:
                wait = 5 * (attempt + 1)
                print(f"    ! {tag} HTTP {exc.code}，第 {attempt + 1} 轮，等 {wait}s")
            time.sleep(wait)
        except Exception as exc:                                   # noqa: BLE001
            last = exc
            wait = 10 * (attempt + 1)
            print(f"    ! {tag} 网络异常：{exc}；第 {attempt + 1} 轮，等 {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"查询连续失败：{tag}：{last}")


def val(binding, key):
    """取 SPARQL binding 的字符串值，缺失返回 None。"""
    node = binding.get(key)
    return node.get("value") if node else None


def lang_of(binding, key):
    """取字面量的语言标记，缺失返回 None。"""
    node = binding.get(key)
    return (node or {}).get("xml:lang")


def qid(uri):
    """http://www.wikidata.org/entity/Q123 -> Q123"""
    return uri.rsplit("/", 1)[-1] if uri else None


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------- 各阶段

def fetch_seeds(limit=None):
    """阶段 1：种子航司。"""
    values = " ".join(f"wd:{c}" for c in SEED_COUNTRIES)
    q = (
        PREFIX
        + f"SELECT DISTINCT ?e WHERE {{\n"
        f"  ?e wdt:P31/wdt:P279* wd:{AIRLINE_CLASS} ;\n"
        f"     wdt:P17 ?c .\n"
        f"  VALUES ?c {{ {values} }}\n"
        f"}}"
    )
    rows, ms = sparql(q, "seeds")
    ids = sorted({qid(val(r, "e")) for r in rows if val(r, "e")}, key=lambda x: int(x[1:]))
    print(f"==> 1/6 种子航司 {len(ids)} 家（{ms} ms）")
    if limit:
        ids = ids[:limit]
        print(f"    （--limit 生效，只取前 {len(ids)} 家）")
    return ids


def fetch_meta(ids, tag, with_tc=True):
    """
    阶段 2/4：分批抓标签、类型、国家。

    注意：**不要**把 labels / P31 / P17 / altLabel 放进同一条查询的四个 OPTIONAL 里——
    它们会做笛卡尔积（6 标签 × 3 类型 × 2 国家 × 5 别名 = 180 行/实体），
    184 个实体就能把 QLever 读到超时。拆成两条轻查询，各自都是纯 join，快且稳定。
    别名（altLabel）本阶段不需要，交给 T1.3 构造 MERGE_ENTITY 时再取。
    """
    meta = {}
    zh_filter = '"zh-hans","zh-cn","zh","zh-hant","zh-tw"'

    for i, batch in enumerate(chunks(ids, BATCH), 1):
        values = " ".join(f"wd:{x}" for x in batch)

        # 2a. 标签：只取需要的语言，纯 join，无 OPTIONAL
        q_lab = (
            PREFIX
            + "SELECT ?e ?l WHERE {\n"
            f"  VALUES ?e {{ {values} }}\n"
            f'  ?e rdfs:label ?l . FILTER(lang(?l) IN ({zh_filter},"en"))\n'
            "}"
        )
        rows, ms = sparql(q_lab, f"{tag}_lab{i}")
        for r in rows:
            eid = qid(val(r, "e"))
            lv = val(r, "l")
            if eid and lv:
                m = meta.setdefault(eid, {"labels": {}, "type_qids": set(),
                                          "countries": set(), "aliases": set()})
                m["labels"].setdefault((lang_of(r, "l") or "und").lower(), lv)
        print(f"    {tag} 标签{i}: {len(rows)} 行（{ms} ms）")

        # 2b. 类型 + 国家：两个 OPTIONAL，基数很小，不会爆
        if not with_tc:
            continue                                   # 类节点只取标签，省一次配额
        q_tc = (
            PREFIX
            + "SELECT ?e ?type ?country WHERE {\n"
            f"  VALUES ?e {{ {values} }}\n"
            "  OPTIONAL { ?e wdt:P31 ?type }\n"
            "  OPTIONAL { ?e wdt:P17 ?country }\n"
            "}"
        )
        rows, ms = sparql(q_tc, f"{tag}_tc{i}")
        for r in rows:
            eid = qid(val(r, "e"))
            if not eid:
                continue
            m = meta.setdefault(eid, {"labels": {}, "type_qids": set(),
                                      "countries": set(), "aliases": set()})
            tv, cv = val(r, "type"), val(r, "country")
            if tv:
                m["type_qids"].add(qid(tv))
            if cv:
                m["countries"].add(qid(cv))
        print(f"    {tag} 类型国家{i}: {len(rows)} 行（{ms} ms）")

    return meta


def fetch_neighbors(seed_ids):
    """阶段 3：六条白名单关系的一跳邻居，返回 (h, r, t) 三元组列表。"""
    triples = []
    props = " ".join(f"wdt:{p}" for p in WHITELIST)
    for i, batch in enumerate(chunks(seed_ids, BATCH), 1):
        values = " ".join(f"wd:{x}" for x in batch)
        q = (
            PREFIX
            + "SELECT ?e ?p ?o WHERE {\n"
            f"  VALUES ?e {{ {values} }}\n"
            f"  VALUES ?p {{ {props} }}\n"
            "  ?e ?p ?o .\n"
            "}"
        )
        rows, ms = sparql(q, f"hop{i}")
        for r in rows:
            h, p, t = qid(val(r, "e")), val(r, "p"), val(r, "o")
            if h and p and t:
                triples.append((h, p.rsplit("/", 1)[-1], qid(t)))
        print(f"    hop{i}: {len(batch)} 种子 / {len(rows)} 条边（{ms} ms）")
    return triples


def fetch_class_parents(class_ids):
    """阶段 5c：类型类之间的 P279 层级，REFINE_TYPE 需要。"""
    if not class_ids:
        return []
    out = []
    for i, batch in enumerate(chunks(sorted(class_ids, key=lambda x: int(x[1:])), BATCH), 1):
        values = " ".join(f"wd:{x}" for x in batch)
        q = (
            PREFIX
            + "SELECT ?c ?s WHERE {\n"
            f"  VALUES ?c {{ {values} }}\n"
            "  ?c wdt:P279 ?s .\n"
            "}"
        )
        rows, _ = sparql(q, f"p279_{i}")
        for r in rows:
            out.append((qid(val(r, "c")), "P279", qid(val(r, "s"))))
    return out


# ---------------------------------------------------------------- 组装

def pick_zh(labels):
    """按 zh-hans -> zh-cn -> zh -> zh-hant -> zh-tw 回退，返回 (文本, 语言)。"""
    for lang in ZH_ORDER:
        if lang in labels:
            return labels[lang], lang
    return None, None


def build_entities(seed_ids, meta, extra_ids):
    """把 meta 转成实体字典；extra_ids 里的类节点与国家节点也一并纳入。"""
    ents = {}
    all_ids = set(seed_ids) | set(meta) | set(extra_ids)
    for eid in all_ids:
        m = meta.get(eid, {"labels": {}, "type_qids": set(), "countries": set(), "aliases": set()})
        zh, lang_src = pick_zh(m["labels"])
        ents[eid] = {
            "id": eid,
            "label_zh": zh,
            "label_en": m["labels"].get("en"),
            "lang_source": lang_src,
            "type": None,              # T1.2 才做正式类型映射，这里先放主类型的中文标签
            "type_qids": sorted(m["type_qids"]),
            "country": sorted(m["countries"])[0] if m["countries"] else None,
            "aliases": sorted(m["aliases"]),
            "is_seed": eid in set(seed_ids),
        }
    return ents


def make_edge(h, r, t):
    return {
        "h": h, "r": r, "t": t, "source": r,
        "version": "v1", "valid_from": None, "valid_to": None, "superseded_by": None,
    }


def dedupe_edges(edges):
    """去重，并丢掉自环（如「中国 P17 中国」——国家节点的 P17 会指回自己，
    这在后续计数题里会造成双计，且语义上无意义）。"""
    seen, out, self_loops = set(), [], 0
    for e in edges:
        if e["h"] == e["t"]:
            self_loops += 1
            continue
        k = (e["h"], e["r"], e["t"])
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    if self_loops:
        print(f"    丢弃自环 {self_loops} 条")
    return out


def prune(ents, edges):
    """先丢无中文名的实体，再迭代去孤儿，直到稳定。"""
    stats = {"no_zh": 0, "orphan": 0}

    for eid in [k for k, v in ents.items() if not v["label_zh"]]:
        del ents[eid]
        stats["no_zh"] += 1

    while True:
        alive = set(ents)
        edges = [e for e in edges if e["h"] in alive and e["t"] in alive]
        deg = {}
        for e in edges:
            deg[e["h"]] = deg.get(e["h"], 0) + 1
            deg[e["t"]] = deg.get(e["t"], 0) + 1
        dead = [k for k in ents if deg.get(k, 0) == 0]
        if not dead:
            return ents, edges, stats
        for d in dead:
            del ents[d]
            stats["orphan"] += 1


def simplify(ents, enabled):
    """繁简统一：只在回退到 zh / zh-hant / zh-tw 时才需要处理。"""
    suspects = [e for e in ents.values() if e["lang_source"] in NEEDS_CONVERT]
    info = {"suspect": len(suspects), "converted": 0, "tool": None}
    if not enabled or not suspects:
        return info
    try:
        import zhconv                                        # 纯 Python，无编译依赖
    except ImportError:
        info["tool"] = "未安装"
        return info
    for e in suspects:
        new = zhconv.convert(e["label_zh"], "zh-hans")
        if new and new != e["label_zh"]:
            e["label_zh"] = new
            info["converted"] += 1
    info["tool"] = "zhconv"
    return info


def check(ents, edges, simp):
    """六项验收，返回 (指标字典, 是否全部通过)。"""
    alive = set(ents)
    deg = {k: 0 for k in alive}
    for e in edges:
        deg[e["h"]] = deg.get(e["h"], 0) + 1
        deg[e["t"]] = deg.get(e["t"], 0) + 1
    no_zh = [k for k, v in ents.items() if not v["label_zh"]]
    orphan = [k for k in alive if deg.get(k, 0) == 0]
    no_source = [e for e in edges if not e.get("source")]

    m = {
        "n_entities": len(ents),
        "n_edges": len(edges),
        "zh_coverage": 1.0 if not no_zh else 1 - len(no_zh) / max(len(ents), 1),
        "n_no_zh": len(no_zh),
        "n_orphan": len(orphan),
        "n_no_source": len(no_source),
        "n_seed": sum(1 for v in ents.values() if v["is_seed"]),
        "type_edge_ratio": 0.0,
        "simp": simp,
    }
    prop_count = {}
    for e in edges:
        prop_count[e["r"]] = prop_count.get(e["r"], 0) + 1
    m["props"] = prop_count
    m["type_edge_ratio"] = (prop_count.get("P31", 0) + prop_count.get("P17", 0)) / max(len(edges), 1)

    ok = (
        400 <= m["n_entities"] <= 600
        and 1500 <= m["n_edges"] <= 2500
        and not no_zh
        and not orphan
        and not no_source
    )
    return m, ok


# ---------------------------------------------------------------- 主流程

def main():
    global ENDPOINT
    ap = argparse.ArgumentParser(description="T1.1 取航空子图")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出路径")
    ap.add_argument("--limit", type=int, default=None, help="只取前 N 个种子（冒烟测试）")
    ap.add_argument("--no-convert", action="store_true", help="不做繁简转换，只统计可疑条数")
    ap.add_argument("--endpoint", default=ENDPOINT,
                    help="SPARQL 端点。qlever.dev 被限流时可用 "
                         "https://wikidata.demo.openlinksw.com/sparql 兜底"
                         "（换源会在 meta.endpoint 里留痕，论文数据卡需注明）")
    args = ap.parse_args()
    ENDPOINT = args.endpoint

    t_start = time.time()

    seed_ids = fetch_seeds(args.limit)

    print("==> 2/6 抓种子元数据（标签 / 类型 / 国家 / 别名）")
    meta = fetch_meta(seed_ids, "meta_seed")

    print("==> 3/6 抓一跳邻居")
    hop = fetch_neighbors(seed_ids)
    neighbor_ids = sorted({t for _, _, t in hop}, key=lambda x: int(x[1:]))
    print(f"    邻居去重后 {len(neighbor_ids)} 个")

    print("==> 4/6 抓邻居元数据")
    meta.update(fetch_meta(neighbor_ids, "meta_hop"))

    print("==> 5/6 补类型边 / 国家边 / 类型层级")
    ents = build_entities(seed_ids, meta, set())

    # 类型类与国家节点也要成为实体，否则类型边会指向不存在的节点（悬空边）
    class_ids = set()
    for v in ents.values():
        class_ids |= set(v["type_qids"])
    country_ids = {c for v in ents.values() if v["country"] for c in [v["country"]]}
    extra_ids = class_ids | country_ids
    missing = sorted(extra_ids - set(meta), key=lambda x: int(x[1:]))
    if missing:
        print(f"    补抓 {len(missing)} 个类 / 国家节点的标签")
        meta.update(fetch_meta(missing, "meta_cls", with_tc=False))
    ents = build_entities(seed_ids, meta, extra_ids)

    edges = [make_edge(h, r, t) for h, r, t in hop]
    for eid, v in ents.items():
        for c in v["type_qids"]:
            edges.append(make_edge(eid, "P31", c))
        if v["country"]:
            edges.append(make_edge(eid, "P17", v["country"]))
    edges += [make_edge(h, r, t) for h, r, t in fetch_class_parents(class_ids)]
    edges = dedupe_edges(edges)
    print(f"    补边后共 {len(edges)} 条")

    print("==> 6/6 修剪 + 繁简统一 + 写盘")
    ents, edges, pstats = prune(ents, edges)
    print(f"    丢弃无中文名 {pstats['no_zh']} 个；丢弃孤儿 {pstats['orphan']} 个")

    simp = simplify(ents, enabled=not args.no_convert)

    # 主类型：取第一个存在于实体集中的 P31 类的中文名（数据驱动，不硬编码 QID）
    for v in ents.values():
        label = None
        for c in v["type_qids"]:
            if c in ents and ents[c]["label_zh"]:
                label = ents[c]["label_zh"]
                break
        v["type"] = label or "未知"

    order = lambda x: int(x["id"][1:]) if x["id"][1:].isdigit() else 10 ** 9
    ents_list = sorted(ents.values(), key=order)
    edges.sort(key=lambda e: (order({"id": e["h"]}), e["r"], order({"id": e["t"]})))

    m, ok = check(ents, edges, simp)
    payload = {
        "meta": {
            "version": "v1",
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "endpoint": ENDPOINT,
            "seeds_requested": len(seed_ids),
            "seed_class": AIRLINE_CLASS,
            "seed_countries": SEED_COUNTRIES,
            "whitelist_props": WHITELIST,
            "fanout": "1-hop",
            "n_entities": m["n_entities"],
            "n_edges": m["n_edges"],
            "zh_dropped": pstats["no_zh"],
            "orphan_dropped": pstats["orphan"],
            "simplify": simp,
            "idempotent_hash": None,       # 下面回填
        },
        "entities": ents_list,
        "edges": edges,
    }
    h = hashlib.sha1(
        ("|".join(sorted(ents)) + "||" + "|".join(sorted(f'{e["h"]},{e["r"]},{e["t"]}' for e in edges))).encode()
    ).hexdigest()[:16]
    payload["meta"]["idempotent_hash"] = h

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(
        json.dumps({"endpoint": ENDPOINT, "queries": LOG}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # ---------------- 汇报 ----------------
    print()
    print("=" * 62)
    print(f"实体 {m['n_entities']}（种子 {m['n_seed']}）   边 {m['n_edges']}   耗时 {time.time() - t_start:.1f}s")
    print(f"中文名覆盖率 {m['zh_coverage'] * 100:.1f}%   无中文名 {m['n_no_zh']}   孤儿 {m['n_orphan']}")
    print(f"缺 source 的边 {m['n_no_source']}   类型+国家边占比 {m['type_edge_ratio'] * 100:.1f}%")
    print(f"繁简：可疑 {simp['suspect']} 条，实际转换 {simp['converted']} 条，工具 {simp['tool'] or '未启用'}")
    print("边按属性分布：" + "  ".join(f"{k}={v}" for k, v in sorted(m["props"].items(), key=lambda x: -x[1])))
    print(f"实体·边集合哈希 {h}（两次运行应一致）")
    print(f"→ {out}")
    print("=" * 62)
    if not ok:
        print("!! 六项验收未全部通过，请对照 reports/t11_check.md 的判据处理")
        return 1
    print("六项验收全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
