#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.1 子图独立校验
=================
刻意**不复用** fetch_subgraph.py 的任何函数——校验脚本与被校验对象共享代码，
等于自己给自己打分。

做四件事：
1. 结构自检：实体/边规模、中文名覆盖、孤儿、悬空边、source 完整性、属性分布
2. 幂等核对：把「实体 id 集合 + 边集合」的哈希与侧车文件比对（两次运行的产物应一致）
3. 语义抽检：从图里自己挑出目标实体，再用独立 SPARQL 反查图里的说法对不对
4. 人工复核清单：随机抽 10 个实体打印中英文名，供人眼判断

用法：
    python scripts/verify_subgraph.py                      # 默认校验 data/graph_v1.json
    python scripts/verify_subgraph.py data/a.json data/b.json   # 核对两个产物是否一致
"""

import hashlib
import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://qlever.dev/api/wikidata"
PREFIX = (
    "PREFIX wd: <http://www.wikidata.org/entity/>\n"
    "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
)
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"


# ---------------------------------------------------------------- 小工具

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fingerprint(g):
    """实体 id 集合 + 边集合的哈希，与 built_at 无关，用于幂等比对。"""
    ents = sorted(e["id"] for e in g["entities"])
    eds = sorted(f'{e["h"]},{e["r"]},{e["t"]}' for e in g["edges"])
    raw = "|".join(ents) + "||" + "|".join(eds)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def ask(query):
    """独立查一次端点（与产物 meta 里记录的源保持一致），带缓存；限流时返回 None 而不是崩掉。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((ENDPOINT + "\n" + query).encode("utf-8")).hexdigest()
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            pass
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = ENDPOINT + "?query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"Accept": "application/sparql-results+json"})
    try:
        with opener.open(req, timeout=120) as resp:
            rows = json.load(resp).get("results", {}).get("bindings", [])
        cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows
    except urllib.error.HTTPError as exc:
        print(f"    !! 反查被拒（HTTP {exc.code}），该项记为「未能核对」")
        return None
    except Exception as exc:                                       # noqa: BLE001
        print(f"    !! 反查失败（{exc}），该项记为「未能核对」")
        return None


# ---------------------------------------------------------------- 1. 结构自检

def structure(g):
    ents = {e["id"]: e for e in g["entities"]}
    edges = g["edges"]
    deg = {k: 0 for k in ents}
    dangling = []
    no_source = []
    for e in edges:
        if not e.get("source"):
            no_source.append(e)
        for k in (e["h"], e["t"]):
            if k in deg:
                deg[k] += 1
        if e["h"] not in ents or e["t"] not in ents:
            dangling.append(e)
    no_zh = [k for k, v in ents.items() if not v.get("label_zh")]
    orphan = [k for k, v in deg.items() if v == 0]
    props = {}
    for e in edges:
        props[e["r"]] = props.get(e["r"], 0) + 1

    print("── 1. 结构自检 ─────────────────────────────")
    print(f"实体 {len(ents)}（种子 {sum(1 for v in ents.values() if v.get('is_seed'))}）")
    print(f"边   {len(edges)}")
    print(f"中文名覆盖率 {100 * (1 - len(no_zh) / max(len(ents), 1)):.1f}%（缺 {len(no_zh)}）")
    print(f"孤儿 {len(orphan)}   悬空边 {len(dangling)}   缺 source {len(no_source)}")
    print("属性分布：" + "  ".join(f"{k}={v}" for k, v in sorted(props.items(), key=lambda x: -x[1])))
    ok = (400 <= len(ents) <= 600) and (1500 <= len(edges) <= 2500) \
        and not no_zh and not orphan and not no_source
    print("结构验收：" + ("通过" if ok else "未通过"))
    return ents, ok


# ---------------------------------------------------------------- 2. 幂等

def idempotent(g, sidecar):
    fp = fingerprint(g)
    print("\n── 2. 幂等核对 ─────────────────────────────")
    print(f"本次指纹 {fp}")
    if sidecar.exists():
        prev = sidecar.read_text(encoding="utf-8").strip()
        print(f"上次指纹 {prev}")
        if prev == fp:
            print("两次一致")
            return True
        print("!! 两次不一致——跑了两遍出现的差异，说明取图过程不确定（排序/随机/实时数据变动）")
        return False
    sidecar.write_text(fp, encoding="utf-8")
    print("首次运行，已写入侧车文件；再跑一次即可比对")
    return True


# ---------------------------------------------------------------- 3. 语义抽检

def spot_checks(ents, edges):
    print("\n── 3. 语义抽检（图里的说法 vs 独立反查）────────")
    out = {}
    attempted = 0
    unverified = 0

    def targets(h, r):
        return {e["t"] for e in edges if e["h"] == h and e["r"] == r}

    # 3.1 挑一家航空公司，核对它的「航空枢纽 P113」
    airlines = [e for e in ents.values() if e.get("is_seed") and targets(e["id"], "P113")]
    if airlines:
        ent = airlines[0]
        mine = targets(ent["id"], "P113")
        attempted += 1
        rows = ask(PREFIX + f"SELECT ?o WHERE {{ wd:{ent['id']} wdt:P113 ?o }}")
        if rows is None:
            unverified += 1
        if rows is not None:
            truth = {r["o"]["value"].rsplit("/", 1)[-1] for r in rows}
            same = mine == truth
            print(f"[3.1] {ent['label_zh']}（{ent['id']}）枢纽：图 {len(mine)} 个 / 库 {len(truth)} 个 → "
                  + ("一致" if same else f"不一致（图独有 {sorted(mine - truth)}，库独有 {sorted(truth - mine)}）"))
            out["hub"] = same

    # 3.2 挑一个机场，核对它的国家 P17
    airports = [e for e in ents.values()
                if any(ee["t"] == e["id"] and ee["r"] in ("P113", "P121") for ee in edges)]
    airports = [e for e in airports if e.get("country")]
    if airports:
        ent = airports[0]
        attempted += 1
        rows = ask(PREFIX + f"SELECT ?c WHERE {{ wd:{ent['id']} wdt:P17 ?c }}")
        if rows is None:
            unverified += 1
        if rows is not None:
            truth = {r["c"]["value"].rsplit("/", 1)[-1] for r in rows}
            same = ent["country"] in truth
            print(f"[3.2] {ent['label_zh']}（{ent['id']}）国家：图 {ent['country']} / 库 {sorted(truth)} → "
                  + ("一致" if same else "不一致"))
            out["country"] = same

    # 3.3 挑一个制造商，核对它的下游（哪些航司用它）
    #      注意：P176 从航司出发为 0 条（制造商是二跳），所以这一项在本图上通常没有候选，
    #      不是 bug。见 docs/data_card.md 第三节。
    makers = [e for e in ents.values() if any(ee["t"] == e["id"] and ee["r"] == "P176" for ee in edges)]
    if not makers:
        print("[3.3] 图内无 P176 边（制造商需二跳，本图未取），该项跳过")
    if makers:
        ent = makers[0]
        mine = {ee["h"] for ee in edges if ee["t"] == ent["id"] and ee["r"] == "P176"}
        attempted += 1
        rows = ask(PREFIX + f"SELECT ?h WHERE {{ ?h wdt:P176 wd:{ent['id']} }} LIMIT 500")
        if rows is None:
            unverified += 1
        if rows is not None:
            truth = {r["h"]["value"].rsplit("/", 1)[-1] for r in rows}
            # 库里的全集必然包含图里的子集（我们只取了一部分种子），所以只查「图里的边是否都真」
            bogus = mine - truth
            print(f"[3.3] {ent['label_zh']}（{ent['id']}）被 {len(mine)} 家航司使用："
                  + ("全部能在库里找到" if not bogus else f"有 {len(bogus)} 条库中不存在 {sorted(bogus)}"))
            out["maker"] = not bogus

    if not out:
        if attempted:
            print(f"（{attempted} 项全部因限流未能反查，稍后重跑本脚本即可补上）")
            return None, unverified
        print("（图里没有可用于抽检的实体，可能是 --limit 冒烟产物）")
        return None, 0
    return all(out.values()), unverified


# ---------------------------------------------------------------- 4. 人工复核清单

def sample(ents, n=10, seed=20261116):
    print(f"\n── 4. 人工复核清单（随机 {n} 个，人眼判断中文名是否通顺正确）──")
    items = sorted(ents.values(), key=lambda x: x["id"])
    random.Random(seed).shuffle(items)
    for i, e in enumerate(items[:n], 1):
        print(f"{i:>2}. {e['label_zh']:<16} | {e.get('label_en') or '-':<32} | {e['type']} | {e['id']}")


# ---------------------------------------------------------------- main

def main():
    global ENDPOINT
    args = sys.argv[1:]
    if len(args) >= 2:
        a, b = load(args[0]), load(args[1])
        fa, fb = fingerprint(a), fingerprint(b)
        print(f"{args[0]}: {fa}")
        print(f"{args[1]}: {fb}")
        print("一致" if fa == fb else "不一致")
        return 0 if fa == fb else 1

    path = Path(args[0]) if args else ROOT / "data" / "graph_v1.json"
    if not path.exists():
        print(f"找不到 {path}，先跑 fetch_subgraph.py")
        return 1
    g = load(path)
    # 反查必须用产出这份图的同一个源，否则比的是两个快照，会出假告警
    ENDPOINT = g["meta"].get("endpoint", ENDPOINT)
    print(f"校验 {path}（version={g['meta'].get('version')}, 构建于 {g['meta'].get('built_at')}）")
    print(f"数据源 {ENDPOINT}\n")

    ents, ok1 = structure(g)
    ok2 = idempotent(g, path.with_suffix(".hash"))
    ok3, unverified = spot_checks(ents, g["edges"])
    sample(ents)

    print("\n── 结论 ───────────────────────────────────")
    if ok3 is None:
        sem = "未能核对"
    elif ok3 and unverified:
        sem = f"部分通过（{unverified} 项因限流未核对）"
    else:
        sem = "通过" if ok3 else "未通过"
    print(f"结构 {'通过' if ok1 else '未通过'}　幂等 {'通过' if ok2 else '未通过'}　语义抽检 {sem}")
    print("人眼复核：上面 10 个中文名是否都正确、不重名、不带括号消歧后缀")
    return 0 if (ok1 and ok2 and ok3 is not False) else 1


if __name__ == "__main__":
    sys.exit(main())
