#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T2.1 + T2.2 模板池与题集生成
============================
产出 `data/questions_v1.json`：100 道结构化题（32 count / 24 set / 16 bool / 28 hop2），
每题都能被 `labels/solver.py` 唯一求解，题面由模板生成。

四条出题纪律（写进论文数据节，也是本脚本的自检项）：
1. **只出图能答、且语义成立**的题：类×关系按 `CLASS_REL` 白名单配对，避开
   「城市有母公司」「国际机场有运营机型」这类无意义组合；并避开数据卡的三处
   已知偏差（无航线网络、P176 为 0、外围噪声节点）。
2. **同一批题跑五个分支**：不按变更类型定制题面，否则「差异」里混进了「题不一样」。
3. **不预设答案**：本脚本只生成题；gold 由 solver 独立求解，先验由 A 单独填。
4. **地区称谓按中国官方表述**：见 `COUNTRY_FIX`，不直接沿用 Wikidata 标签。

用法：
    python scripts/gen_questions.py            # 生成 + 自检
    python scripts/gen_questions.py --check    # 只自检
"""

import argparse
import collections
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GRAPH = DATA / "graph_v1.json"
OUT = DATA / "questions_v1.json"

SEED = 20261117
QUOTA = {"count": 32, "set": 24, "bool": 16, "hop2": 28}

# 只保留领域内类；机场子类是 REFINE/SPLIT 的对象，必须有
CLASSES = ["Q46970", "Q1248784", "Q644371", "Q94993988", "Q1057026",
           "Q28692646", "Q5124659", "Q837800", "Q15056993", "Q515"]

# 类 × 关系的合法配对：空列表表示该类不该问「拥有某关系」
CLASS_REL = {
    "Q46970": ["P113", "P749", "P121", "P159", "P127"],   # 航空公司
    "Q1057026": ["P113", "P749", "P121", "P159", "P127"],  # 货运航空公司
    "Q1248784": [], "Q644371": [], "Q94993988": [],       # 机场类：出边只有 P31/P17
    "Q28692646": [], "Q5124659": [], "Q837800": [],
    "Q15056993": [],                                      # 飞机系列
    "Q515": [],                                           # 城市
}

REL_NAME = {"P113": "航空枢纽", "P749": "母公司", "P121": "运营机型",
            "P159": "总部所在地", "P127": "所属集团", "P17": "国家/地区"}

# 地区称谓：Wikidata 标签不能直接进题面
COUNTRY_FIX = {"Q148": "中国", "Q865": "中国台湾地区", "Q8646": "中国香港",
               "Q14773": "中国澳门", "Q884": "韩国", "Q17": "日本", "Q145": "英国"}
BAD_STRINGS = ["中华民国"]

TPL = {
    "count_class": ["图里一共有多少{cls}？", "一共有多少{cls}？", "统计一下{cls}的总数。"],
    "count_class_country": ["{cty}境内有多少{cls}？", "属于{cty}的{cls}有多少？"],
    "count_with_rel": ["有多少{cls}至少有一个{rel}？", "拥有{rel}的{cls}有多少家？"],
    "count_rel": ["{head}有几个{rel}？", "{head}名下的{rel}有几个？"],
    "list_rel": ["{head}的{rel}分别是哪些？", "列出{head}的{rel}。"],
    "list_class": ["哪些实体属于{cls}？", "列出所有{cls}。"],
    "universal_rel": ["是不是所有{cls}都有{rel}？", "所有{cls}都具备{rel}吗？"],
    "hop2_distinct": ["{cls}的{rel1}一共分布在几个国家或地区？",
                      "{cls}的{rel1}涉及多少个国家或地区？"],
}

CHANGE_TYPES = ["refine", "restrict", "merge", "split", "all"]


def load():
    d = json.loads(GRAPH.read_text(encoding="utf-8"))
    ents = {e["id"]: e for e in d["entities"]}
    out = collections.defaultdict(list)
    for e in d["edges"]:
        out[e["h"]].append((e["r"], e["t"]))
    return d, ents, out


def cname(ents, q):
    return COUNTRY_FIX.get(q) or ents.get(q, {}).get("label_zh") or q


def stats(ents, out):
    """从图里直接算候选（不用 solver，避免出题被答案牵着走）。"""
    with_rel = collections.defaultdict(dict)
    countries = set()
    for eid, e in ents.items():
        rs = {}
        for r in REL_NAME:
            tails = [t for (rr, t) in out.get(eid, ()) if rr == r]
            if tails:
                rs[r] = tails
        if rs:
            with_rel[eid] = rs
        if e.get("country"):
            countries.add(e["country"])
    return {"with_rel": with_rel, "countries": sorted(countries)}


def build(ents, out, st, rng):
    qs, seen = [], set()

    def add(shape, op, tpl, nl, query, note):
        if any(b in nl for b in BAD_STRINGS):
            return False
        sig = json.dumps(query, sort_keys=True, ensure_ascii=False)
        if sig in seen:
            return False
        seen.add(sig)
        qs.append({"qid": f"Q{len(qs) + 1:03d}", "shape": shape, "template": op,
                   "nl": nl, "query": query, "note": note})
        return True

    def n(shape):
        return sum(1 for q in qs if q["shape"] == shape)

    cls = [c for c in CLASSES if c in ents]

    # ---------- count 32
    for c in rng.sample(cls, min(len(cls), 10)):
        t = rng.choice(TPL["count_class"])
        add("count", "count_class", t, t.format(cls=ents[c]["label_zh"]),
            {"op": "count_class", "class": c}, "类闭包计数")

    # 类 × 国家：只保留图里真有 ≥2 个实例的组合，避免答 0
    pairs = []
    for c in cls:
        for k in st["countries"]:
            m = sum(1 for e in ents.values()
                    if c in (e.get("type_qids") or []) and e.get("country") == k)
            if m >= 2:
                pairs.append((c, k))
    rng.shuffle(pairs)
    for c, k in pairs:
        if n("count") >= 18:
            break
        t = rng.choice(TPL["count_class_country"])
        add("count", "count_class_country", t,
            t.format(cls=ents[c]["label_zh"], cty=cname(ents, k)),
            {"op": "count_class_country", "class": c, "country": k},
            "类×国家交叉计数")

    combos = [(c, r) for c in cls for r in CLASS_REL.get(c, [])]
    rng.shuffle(combos)
    for c, r in combos:
        if n("count") >= 24:
            break
        t = rng.choice(TPL["count_with_rel"])
        add("count", "count_with_rel", t,
            t.format(cls=ents[c]["label_zh"], rel=REL_NAME[r]),
            {"op": "count_with_rel", "class": c, "rel": r}, "存在性计数")

    heads = sorted(h for h, rs in st["with_rel"].items()
                   if any(len(v) >= 2 for v in rs.values()))
    rng.shuffle(heads)
    for h in heads:
        if n("count") >= 30:
            break
        r = max(st["with_rel"][h], key=lambda k: len(st["with_rel"][h][k]))
        t = rng.choice(TPL["count_rel"])
        add("count", "count_rel", t, t.format(head=ents[h]["label_zh"], rel=REL_NAME[r]),
            {"op": "count_rel", "head": h, "rel": r}, "单实体关系计数")

    # 补集类题（SPLIT 唯一的「该变」来源：v1 无此类 → 0，v2 有 → 177）
    try:
        sch = json.loads((DATA / "schema.json").read_text(encoding="utf-8"))
        comp = sch["ops_plan"]["split_concept"]["complement"]
        t = rng.choice(TPL["count_class"])
        add("count", "count_class", t, t.format(cls=comp["label"]),
            {"op": "count_class", "class": comp["qid"]},
            "补集类计数（split 分支新增类，v1 为 0）")
        t2 = rng.choice(TPL["count_with_rel"])
        add("count", "count_with_rel", t2,
            t2.format(cls=comp["label"], rel=REL_NAME["P113"]),
            {"op": "count_with_rel", "class": comp["qid"], "rel": "P113"},
            "补集类×关系计数（split 分支新增类，v1 为 0）")
    except Exception:                                              # noqa: BLE001
        pass

    # ---------- set 24
    for c in rng.sample(cls, min(len(cls), 8)):
        t = rng.choice(TPL["list_class"])
        add("set", "list_class", t, t.format(cls=ents[c]["label_zh"]),
            {"op": "list_class", "class": c}, "类闭包枚举")
    cand = sorted((h, r) for h, rs in st["with_rel"].items()
                  for r, v in rs.items() if len(v) >= 2)
    rng.shuffle(cand)
    for h, r in cand:
        if n("set") >= QUOTA["set"]:
            break
        t = rng.choice(TPL["list_rel"])
        add("set", "list_rel", t, t.format(head=ents[h]["label_zh"], rel=REL_NAME[r]),
            {"op": "list_rel", "head": h, "rel": r}, "单实体关系枚举")

    # ---------- bool 16：只问航司类 × 枢纽/母公司/机型，避免真空真
    combos = [(c, r) for c in ("Q46970", "Q1057026") if c in ents
              for r in ("P113", "P749", "P121", "P159", "P127")]
    rng.shuffle(combos)
    for c, r in combos:
        if n("bool") >= QUOTA["bool"]:
            break
        t = rng.choice(TPL["universal_rel"])
        add("bool", "universal_rel", t,
            t.format(cls=ents[c]["label_zh"], rel=REL_NAME[r]),
            {"op": "universal_rel", "class": c, "rel": r}, "全称判断")
    for c in [x for x in cls if x not in ("Q46970", "Q1057026")]:
        if n("bool") >= QUOTA["bool"]:
            break
        t = rng.choice(TPL["universal_rel"])
        add("bool", "universal_rel", t,
            t.format(cls=ents[c]["label_zh"], rel=REL_NAME["P17"]),
            {"op": "universal_rel", "class": c, "rel": "P17"}, "全称判断（国家维度）")

    # ---------- hop2 28
    combos = [(c, r) for c in ("Q46970", "Q1057026") if c in ents
              for r in ("P113", "P159", "P749")]
    rng.shuffle(combos)
    for c, r in combos:
        if n("hop2") >= QUOTA["hop2"]:
            break
        t = rng.choice(TPL["hop2_distinct"])
        add("hop2", "hop2_distinct", t,
            t.format(cls=ents[c]["label_zh"], rel1=REL_NAME[r]),
            {"op": "hop2_distinct", "class": c, "rel1": r, "rel2": "P17"},
            f"二跳：{REL_NAME[r]} → 国家")
    # 不足时换成实体起点的二跳（同一语义，起点是单个航司）
    heads = [h for h, rs in st["with_rel"].items() if len(rs.get("P113", [])) >= 2]
    rng.shuffle(heads)
    for h in heads:
        if n("hop2") >= QUOTA["hop2"]:
            break
        t = "{head}的航空枢纽涉及多少个国家或地区？"
        add("hop2", "hop2_head", t, t.format(head=ents[h]["label_zh"]),
            {"op": "hop2_head", "head": h, "rel1": "P113", "rel2": "P17"},
            "二跳（实体起点）：枢纽 → 国家")

    return qs


def check(qs, ents):
    errs = []
    if len(qs) != 100:
        errs.append(f"题数 {len(qs)} != 100")
    if len({q["qid"] for q in qs}) != len(qs):
        errs.append("qid 重复")
    if len({json.dumps(q["query"], sort_keys=True) for q in qs}) != len(qs):
        errs.append("query 重复")
    by = collections.Counter(q["shape"] for q in qs)
    for s, n in QUOTA.items():
        if by[s] != n:
            errs.append(f"{s} 数量 {by[s]} != 配额 {n}")
    for q in qs:
        if "{" in q["nl"] or "}" in q["nl"]:
            errs.append(f"{q['qid']} 题面残留占位符：{q['nl']}")
        if any(b in q["nl"] for b in BAD_STRINGS):
            errs.append(f"{q['qid']} 题面含不当称谓：{q['nl']}")
        # 类×关系必须合法
        c0 = q["query"].get("class", "")
        # 补集类继承父类的关系域
        allowed = CLASS_REL.get("Q46970", []) if c0.startswith("Q_synth_") \
            else CLASS_REL.get(c0, [])
        if q["template"] == "count_with_rel" and q["query"]["rel"] not in allowed:
            errs.append(f"{q['qid']} 类关系配对非法")
        if q["template"] == "universal_rel":
            c, r = q["query"]["class"], q["query"]["rel"]
            if r != "P17" and r not in CLASS_REL.get(c, []):
                errs.append(f"{q['qid']} 全称题类关系配对非法")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        ents = {e["id"]: e for e in
                json.loads(GRAPH.read_text(encoding="utf-8"))["entities"]}
        errs = check(d["questions"], ents)
        print("自检：", "通过" if not errs else errs)
        return 0 if not errs else 1

    d, ents, out = load()
    qs = build(ents, out, stats(ents, out), random.Random(SEED))
    errs = check(qs, ents)
    doc = {
        "meta": {
            "version": "v1", "n": len(qs), "seed": SEED,
            "source_graph": "data/graph_v1.json",
            "graph_hash": d["meta"]["idempotent_hash"],
            "quota": QUOTA, "branches": CHANGE_TYPES,
            "language_policy": "题面只用中文标签，不出现 QID；地区称谓按中国官方表述",
            "known_gaps": ["无航线网络", "P176 从航司为 0 条", "外围噪声节点不在类池内"],
            "discipline": "本文件只生成题，不含 gold；gold 由 labels/solver.py 独立求解",
        },
        "questions": qs,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写出 {OUT.relative_to(ROOT)}：{len(qs)} 题")
    print("分布：", dict(collections.Counter(q["shape"] for q in qs)))
    print("自检：", "通过" if not errs else errs)
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
