# -*- coding: utf-8 -*-
"""校验本 bundle 的四版图（只用标准库；opencc 可选）。

用法：
  python scripts/verify_variants.py
退出码：结构不变量（孤儿/悬空/自环/source/version/指纹）任一失败 -> 1。
T1.1 的 400-600 / domain 1500 只打印，不决定退出码（各版定位不同）。
"""
import hashlib
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "data"))

FILES = [
    "graph_v1_1.json",
    "graph_v1_1_600.json",
    "graph_v1_2_enriched.json",
    "graph_v1_3_domain1500.json",
]
KNOWN_TRAD = ["仁川國際機場", "內飞地", "大園区", "赤鱲角"]

try:
    from opencc import OpenCC
    T2S = OpenCC("t2s")
except Exception:  # noqa: BLE001
    T2S = None


def fp_of(g):
    ids = sorted(e["id"] for e in g["entities"])
    sig = "|".join(ids) + "#" + "|".join(
        f"{d['h']}>{d['r']}>{d['t']}" for d in sorted(
            g["edges"], key=lambda x: (x["h"], x["r"], x["t"])))
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


print("=" * 110)
print("T1.1 图增强包校验")
print("=" * 110)
print(f"{'文件':<32}{'实体':>5}{'边':>6}{'domain':>7}{'schema':>7}{'P176':>5}{'P931':>5}"
      f"{'alias':>6}{'繁体':>5}{'孤儿':>5}{'悬空':>5}{'自环':>5}  指纹")
all_ok = True
rows = []
for fn in FILES:
    p = os.path.join(DATA, fn)
    if not os.path.exists(p):
        print(f"❌ 缺文件 {fn}")
        all_ok = False
        continue
    g = json.load(open(p, encoding="utf-8"))
    e, d = g["entities"], g["edges"]
    idx = {x["id"] for x in e}
    deg = Counter()
    for x in d:
        deg[x["h"]] += 1
        deg[x["t"]] += 1
    p31 = sum(1 for x in d if x["r"] == "P31")
    p279 = sum(1 for x in d if x["r"] == "P279")
    domain = len(d) - p31 - p279
    p176 = sum(1 for x in d if x["r"] == "P176")
    p931 = sum(1 for x in d if x["r"] == "P931")
    alias = sum(1 for x in e if x.get("aliases"))
    latin = [x["label_zh"] for x in e if not re.search(r"[\u4e00-\u9fff]", x["label_zh"])]
    if T2S:
        trad = [x["label_zh"] for x in e if T2S.convert(x["label_zh"]) != x["label_zh"]]
    else:
        trad = [x["label_zh"] for x in e if x["label_zh"] in KNOWN_TRAD]
    orphan = sum(1 for x in e if deg.get(x["id"], 0) == 0)
    dangling = sum(1 for x in d if x["h"] not in idx or x["t"] not in idx)
    selfloop = sum(1 for x in d if x["h"] == x["t"])
    no_source = sum(1 for x in d if not x.get("source"))
    no_version = sum(1 for x in d if not x.get("version"))
    fp = fp_of(g)
    fp_ok = fp == g.get("meta", {}).get("idempotent_hash")
    ok = (orphan == 0 and dangling == 0 and selfloop == 0
          and no_source == 0 and no_version == 0 and len(trad) == 0 and fp_ok)
    all_ok = all_ok and ok
    print(f"{fn:<32}{len(e):>5}{len(d):>6}{domain:>7}{p31+p279:>7}{p176:>5}{p931:>5}"
          f"{alias:>6}{len(trad):>5}{orphan:>5}{dangling:>5}{selfloop:>5}  {fp}{'' if fp_ok else ' ❌'}")
    rows.append((fn, len(e), len(d), domain, p176, p931, len(latin), len(trad), ok))

print("\nT1.1 定位：")
for fn, n, m, domain, p176, p931, latin, trad, ok in rows:
    print(f"  {fn:<32} 实体 400–600: {'✅' if 400 <= n <= 600 else '❌'} ({n})"
          f"  边 1500–2500: {'✅' if 1500 <= m <= 2500 else '❌'} ({m})"
          f"  domain≥1500: {'✅' if domain >= 1500 else '❌'} ({domain})"
          f"  拉丁例外 {latin}  繁体 {trad}")

print("\n说明：")
print("  - 结构不变量：孤儿/悬空/自环/source/version/指纹 任一失败 -> 退出码 1。")
print("  - 400–600 与 domain≥1500 是 T1.1 指标，各版定位不同，只打印不判失败。")
print("  - 繁体检查优先用 opencc；未安装时只检查 4 条已知标签。")
sys.exit(0 if all_ok else 1)
