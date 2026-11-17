#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.0 前置探针（离线三条 + 联网一条）
====================================
在写 T1.3 的算子之前，先用确定性统计回答四个问题。对应《进度评审_2026-11-16》
第 3 节的 T1.0-a ~ T1.0-d。

    python scripts/probe_t10.py            # 只跑离线三条（b/c/d）
    python scripts/probe_t10.py --with-a   # 额外跑 T1.0-a（需联网，qlever 限流很紧）

输出：
    data/probe_t10.json     结构化结果（供后续脚本与论文引用）
    reports/t10_probe.md    人读报告，每条给判据、实测、触发动作

设计原则：探针只统计、不修改 graph_v1.json；每条判据写死在 CRITERIA 里，
免得事后拿结果反推标准（评审第 3 节明令「不许改先验迁就结果」）。
"""

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "data" / "graph_v1.json"
OUT_JSON = ROOT / "data" / "probe_t10.json"
OUT_MD = ROOT / "reports" / "t10_probe.md"

WHITELIST = ["P121", "P113", "P176", "P749", "P127", "P159"]


# ---------------------------------------------------------------- 工具

def norm(s):
    """标签归一化：NFKC + 去空白/标点 + 小写。用于同名判定。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[\s\-·・,，.。'\"“”‘’()（）\[\]【】]+", "", s)
    return s


# 泛化词表：包含这些词的标签不算「同指」，避免「中国航空」与「中国航空集团」误配。
GENERIC = ["航空", "机场", "公司", "集团", "控股", "国际", "中国", "日本", "韩国",
           "有限", "股份", "航空器", "飞机", "城市", "地区", "省", "市", "县", "区"]


def strip_generic(s):
    for g in GENERIC:
        s = s.replace(g, "")
    return s


# ---------------------------------------------------------------- 载入

def load():
    d = json.loads(GRAPH.read_text(encoding="utf-8"))
    ents = {e["id"]: e for e in d["entities"]}
    edges = d["edges"]
    return d, ents, edges


def class_index(ents, edges):
    """class_qid -> 直接断言的实例集合；以及 P279 父子表。"""
    inst = collections.defaultdict(set)
    parents = collections.defaultdict(set)     # child -> {parent}
    children = collections.defaultdict(set)    # parent -> {child}
    for e in edges:
        if e["r"] == "P31":
            inst[e["t"]].add(e["h"])
        elif e["r"] == "P279":
            parents[e["h"]].add(e["t"])
            children[e["t"]].add(e["h"])
    return inst, parents, children


# ---------------------------------------------------------------- T1.0-b 同指实体

def probe_merge(ents, edges):
    """
    找「可能是同一个东西的两个节点」。三类证据，置信度递减：
      E1 归一化标签完全相同（不同 QID）——若存在，说明社群没合并，可直接用
      E2 一方的 alias 等于另一方的 label
      E3 标签互为包含且去掉泛化词后仍相同（如「国泰航空」vs「国泰航空有限公司」）
    """
    by_label = collections.defaultdict(list)
    for e in ents.values():
        k = norm(e.get("label_zh"))
        if k:
            by_label[k].append(e["id"])

    exact = {k: v for k, v in by_label.items() if len(v) > 1}

    alias_hit = []
    for e in ents.values():
        for a in e.get("aliases") or []:
            k = norm(a)
            if not k or k == norm(e.get("label_zh")):
                continue
            for other in by_label.get(k, []):
                if other != e["id"]:
                    alias_hit.append({"a": e["id"], "b": other, "via": a,
                                      "a_label": e.get("label_zh"),
                                      "b_label": ents[other].get("label_zh")})

    contain = []
    labels = [(e["id"], norm(e.get("label_zh"))) for e in ents.values()]
    labels = [(i, k) for i, k in labels if len(k) >= 5]
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            (ia, ka), (ib, kb) = labels[i], labels[j]
            if ia == ib or not ka or not kb:
                continue
            if ka in kb or kb in ka:
                if strip_generic(ka) and strip_generic(ka) == strip_generic(kb):
                    contain.append({"a": ia, "b": ib,
                                    "a_label": ents[ia]["label_zh"],
                                    "b_label": ents[ib]["label_zh"]})

    # 去重（alias 命中常成对出现）
    seen, alias_u = set(), []
    for h in alias_hit:
        key = tuple(sorted([h["a"], h["b"]]))
        if key not in seen:
            seen.add(key)
            alias_u.append(h)

    seen, contain_u = set(), []
    for h in contain:
        key = tuple(sorted([h["a"], h["b"]]))
        if key not in seen:
            seen.add(key)
            contain_u.append(h)

    return {
        "exact_same_label": [{"ids": v, "labels": [ents[i]["label_zh"] for i in v]}
                             for v in exact.values()],
        "alias_hits": alias_u,
        "containment_hits": contain_u,
        "n_candidates": len(exact) + len(alias_u) + len(contain_u),
    }


# ---------------------------------------------------------------- T1.0-c 取图三项计数

def probe_counts(ents, edges):
    deg = collections.Counter()
    wl_deg = collections.Counter()
    for e in edges:
        deg[e["h"]] += 1
        deg[e["t"]] += 1
        if e["r"] in WHITELIST:
            wl_deg[e["h"]] += 1
    n_ent = len(ents)
    n_zh = sum(1 for e in ents.values() if e.get("label_zh"))
    n_seed = sum(1 for e in ents.values() if e.get("is_seed"))
    n_seed_2wl = sum(1 for e in ents.values() if e.get("is_seed") and wl_deg[e["id"]] >= 2)
    n_2wl = sum(1 for i in ents if wl_deg[i] >= 2)
    return {
        "n_entities": n_ent,
        "n_seeds": n_seed,
        "n_zh_label": n_zh,
        "n_seed_with_2_whitelist": n_seed_2wl,
        "n_any_with_2_whitelist": n_2wl,
        "n_isolated": sum(1 for i in ents if deg[i] == 0),
    }


# ---------------------------------------------------------------- T1.0-d 类型二分

def probe_types(ents, edges):
    """
    对每个类 C 统计：
      direct  : 只断言为 C 的实例数（细化时无处安放的部分）
      via_child: 已断言为某个子类的实例数
      n_child : 直接子类个数
    并给出「干净二分」候选：n_child == 2 且 direct 占比低。
    """
    inst, parents, children = class_index(ents, edges)
    rows = []
    for c, s in inst.items():
        kids = children.get(c, set())
        # 只统计在图内、且本身有实例的子类
        kids = {k for k in kids if inst.get(k)}
        direct = len(s)
        via = 0
        for k in kids:
            via += len(inst[k] - s)
        rows.append({
            "class": c,
            "label": ents.get(c, {}).get("label_zh"),
            "n_instances_direct": direct,
            "n_children": len(kids),
            "children": [{"qid": k,
                          "label": ents.get(k, {}).get("label_zh"),
                          "n": len(inst[k])} for k in sorted(kids)],
            "n_instances_via_child": via,
            "direct_ratio": round(direct / max(direct + via, 1), 3),
        })
    rows.sort(key=lambda r: -(r["n_instances_direct"] + r["n_instances_via_child"]))

    binary = [r for r in rows if r["n_children"] == 2]
    binary.sort(key=lambda r: r["direct_ratio"])
    return {"classes": rows, "binary_candidates": binary,
            "n_classes_with_instances": len(rows)}


# ---------------------------------------------------------------- T1.0-a 时间限定词

def probe_qualifiers(with_a=False, endpoint=None):
    """
    子图内 P121 边带 P580/P582 的占比。需要一条 SPARQL；qlever 限流极紧，
    因此带磁盘缓存（复用 T1.1 的 cache 目录，key 含端点）。
    """
    if not with_a:
        # 没加 --with-a 时不许把上次的联网结果冲掉：G0 闸门每次都会跑本脚本，
        # 若直接返回 skipped，报告会退化成"未测"，等于把已取得的证据丢掉。
        try:
            prev = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("qualifiers", {})
            if prev.get("status") == "ok":
                prev = dict(prev)
                prev["carried_from"] = "上一次 --with-a 的结果（本次未联网）"
                return prev
        except Exception:                                          # noqa: BLE001
            pass
        return {"status": "skipped", "reason": "未加 --with-a，且无历史结果"}
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import fetch_subgraph as F            # 只复用查询层，不复用任何业务逻辑
        if endpoint:
            F.ENDPOINT = endpoint            # 换源必须换缓存 key（F 的实现已把端点算进 key）
    except Exception as exc:                  # noqa: BLE001
        return {"status": "error", "reason": f"无法载入查询层：{exc}"}

    # 不能把 184 个种子塞进 VALUES：GET 的 URL 会 414（Too Long，实测踩过）。
    # 改为在查询里现算种子集（与 T1.1 定义一致），URL 只有 6 个国家 id。
    countries = " ".join(f"wd:{c}" for c in
                         ["Q148", "Q8646", "Q14773", "Q865", "Q17", "Q884"])
    body = (f"  ?e wdt:P31/wdt:P279* wd:Q46970 ; wdt:P17 ?c .\n"
            f"  VALUES ?c {{ {countries} }}\n"
            "  ?e p:P121 ?st .\n"
            "  ?st ps:P121 ?o .\n")
    q = (
        F.PREFIX
        + "SELECT ?n ?nf ?nt WHERE {\n"
          "  { SELECT (COUNT(*) AS ?n) WHERE {\n" + body + "  } }\n"
          "  { SELECT (COUNT(*) AS ?nf) WHERE {\n" + body
          + "    ?st pq:P580 ?f .\n  } }\n"
          "  { SELECT (COUNT(*) AS ?nt) WHERE {\n" + body
          + "    ?st pq:P582 ?t .\n  } }\n"
          "}\n"
    )
    try:
        rows, _ = F.sparql(q, "t10a-p121-qualifiers")
        n = int(F.val(rows[0], "n") or 0) if rows else 0
        nf = int(F.val(rows[0], "nf") or 0) if rows else 0
        nt = int(F.val(rows[0], "nt") or 0) if rows else 0
        return {"status": "ok", "endpoint": F.ENDPOINT,
                "n_p121": n, "n_with_from": nf, "n_with_to": nt,
                "ratio_any": round((nf + nt) / n, 4) if n else None,
                "ratio_from": round(nf / n, 4) if n else None}
    except Exception as exc:                  # noqa: BLE001
        return {"status": "error", "reason": str(exc)[:300]}


# ---------------------------------------------------------------- 判据（先写死）

CRITERIA = {
    "a": {
        "q": "P121 边带 P580 或 P582 的占比",
        "pass": ">=0.30 原方案可行；0.10-0.30 只对带时间的边施加；<0.10 换实现",
    },
    "b": {
        "q": "可识别的同指实体候选对数",
        "pass": ">=8 用真实对；<8 必须人工构造并在论文标注",
    },
    "c": {
        "q": "实体数 / 有中文名数 / 带>=2 条白名单关系数，三者均 >=400",
        "pass": "任一不过则扩东南亚或换领域",
    },
    "d": {
        "q": "存在干净二分（子类两个、直接断言占比低、并集=父类）",
        "pass": "有则用真实二分；无则用「阳性分支+补集」并在论文标注 synthetic",
    },
}


def verdicts(res):
    v = {}
    c = res["counts"]
    v["c"] = "pass" if (c["n_entities"] >= 400 and c["n_zh_label"] >= 400
                        and c["n_any_with_2_whitelist"] >= 400) else "fail"
    b = res["merge"]["n_candidates"]
    v["b"] = "pass" if b >= 8 else "fail"
    d = res["types"]["binary_candidates"]
    clean = [r for r in d if r["direct_ratio"] <= 0.2]
    v["d"] = "pass" if clean else "partial"
    a = res.get("qualifiers", {})
    if a.get("status") == "ok":
        v["a"] = ("pass" if a["ratio_any"] >= 0.30
                  else "partial" if a["ratio_any"] >= 0.10 else "fail")
    else:
        v["a"] = "unverified"
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-a", action="store_true")
    ap.add_argument("--endpoint", default=None,
                    help="备用端点，例如 https://wikidata.demo.openlinksw.com/sparql")
    args = ap.parse_args()

    d, ents, edges = load()
    res = {
        "graph": str(GRAPH.relative_to(ROOT)),
        "idempotent_hash": d["meta"].get("idempotent_hash"),
        "counts": probe_counts(ents, edges),
        "merge": probe_merge(ents, edges),
        "types": probe_types(ents, edges),
        "qualifiers": probe_qualifiers(args.with_a, args.endpoint),
        "criteria": CRITERIA,
    }
    res["verdicts"] = verdicts(res)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- markdown
    c, m, t = res["counts"], res["merge"], res["types"]
    L = []
    L.append("# T1.0 前置探针报告\n")
    L.append(f"对象：`data/graph_v1.json`（指纹 `{res['idempotent_hash']}`）　｜　"
             f"生成：`scripts/probe_t10.py`\n")
    L.append("判据在脚本 `CRITERIA` 里写死，先于结果存在；实测不得反向修改判据。\n")
    L.append("## 结论速览\n")
    L.append("| 探针 | 问题 | 结论 |")
    L.append("|---|---|---|")
    L.append(f"| a | P121 时间限定词占比 | **{res['verdicts']['a']}**"
             f"（{res['qualifiers'].get('ratio_any') if res['qualifiers'].get('status')=='ok' else '未测'}）|")
    L.append(f"| b | 同指实体候选对 | **{res['verdicts']['b']}**（{m['n_candidates']} 对）|")
    L.append(f"| c | 三项计数 ≥400 | **{res['verdicts']['c']}**"
             f"（{c['n_entities']} / {c['n_zh_label']} / {c['n_any_with_2_whitelist']}）|")
    L.append(f"| d | 干净类型二分 | **{res['verdicts']['d']}**（{len(t['binary_candidates'])} 个二子类候选）|\n")

    L.append("## T1.0-c 取图三项计数\n")
    L.append("| 项 | 值 | 判据 |")
    L.append("|---|---|---|")
    L.append(f"| 实体数 | {c['n_entities']} | ≥400 |")
    L.append(f"| 有中文名 | {c['n_zh_label']} | ≥400 |")
    L.append(f"| 带 ≥2 条白名单关系 | {c['n_any_with_2_whitelist']} | ≥400 |")
    L.append(f"| 种子航司 | {c['n_seeds']}（其中 ≥2 条白名单关系 {c['n_seed_with_2_whitelist']}）| — |")
    L.append(f"| 孤立点 | {c['n_isolated']} | 0 |\n")

    L.append("## T1.0-b 同指实体候选\n")
    L.append(f"- 归一化标签完全相同：**{len(m['exact_same_label'])}** 组")
    L.append(f"- 一方 alias 命中另一方 label：**{len(m['alias_hits'])}** 对")
    L.append(f"- 去泛化词后互为包含：**{len(m['containment_hits'])}** 对\n")
    if m["exact_same_label"]:
        L.append("同标签组（前 10）：\n")
        for x in m["exact_same_label"][:10]:
            L.append(f"- {' / '.join(x['labels'])} → `{', '.join(x['ids'])}`")
        L.append("")
    if m["alias_hits"]:
        L.append("alias 命中（前 10）：\n")
        L.append("| A | B | 依据 |")
        L.append("|---|---|---|")
        for x in m["alias_hits"][:10]:
            L.append(f"| {x['a_label']} `{x['a']}` | {x['b_label']} `{x['b']}` | alias=「{x['via']}」|")
        L.append("")
    if m["containment_hits"]:
        L.append("包含关系（前 10，需人工判是否同指）：\n")
        for x in m["containment_hits"][:10]:
            L.append(f"- {x['a_label']} `{x['a']}` ⊂ {x['b_label']} `{x['b']}`")
        L.append("")

    L.append("## T1.0-d 类型细化 / 二分候选\n")
    L.append(f"图内共 {t['n_classes_with_instances']} 个类有实例断言。二子类候选按"
             "「直接断言占比」升序（占比越低，「子类并集=父类」越成立）：\n")
    L.append("| 父类 | 实例(直断) | 子类 | 子类实例 | 直断占比 |")
    L.append("|---|---|---|---|---|")
    for r in t["binary_candidates"][:12]:
        kids = "、".join(f"{k['label']}({k['n']})" for k in r["children"])
        L.append(f"| {r['label']} `{r['class']}` | {r['n_instances_direct']} | {kids} | "
                 f"{r['n_instances_via_child']} | {r['direct_ratio']} |")
    L.append("")
    L.append("规模前 8 的类（看细化空间）：\n")
    L.append("| 类 | 直断实例 | 子类数 | 直断占比 |")
    L.append("|---|---|---|---|")
    for r in t["classes"][:8]:
        L.append(f"| {r['label']} `{r['class']}` | {r['n_instances_direct']} | "
                 f"{r['n_children']} | {r['direct_ratio']} |")
    L.append("")

    q = res["qualifiers"]
    L.append("## T1.0-a P121 时间限定词\n")
    if q.get("status") == "ok":
        L.append(f"- 端点：`{q.get('endpoint')}`（**注意：与 graph_v1 的取数端点可能不同快照**）")
        L.append(f"- P121 边（种子出边）：{q['n_p121']}")
        L.append(f"- 带 P580：{q['n_with_from']}；带 P582：{q['n_with_to']}")
        L.append(f"- **带任一限定词占比：{q['ratio_any']}**\n")
    else:
        L.append(f"- 未取得结果：{q.get('status')} {q.get('reason', '')}\n")

    L.append("## 每条探针的触发动作\n")
    for k in ["a", "b", "c", "d"]:
        L.append(f"- **{k}**（{CRITERIA[k]['q']}）：{CRITERIA[k]['pass']} → 当前判定 "
                 f"`{res['verdicts'][k]}`")
    L.append("")

    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"写出 {OUT_JSON.relative_to(ROOT)} 与 {OUT_MD.relative_to(ROOT)}")
    print("判定：", res["verdicts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
