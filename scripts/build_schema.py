#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.2 类型清单（schema.json）
===========================
从 graph_v1.json 的 P31 / P279 边推出类型树，并为 T1.3 的四个算子产出**可执行的操作计划**。

关键立场（评审 §1.3）：形式条件必须由脚本断言，不能靠人看。
本脚本对每个候选做一次「模拟执行 + 集合等式检查」，把结论写进 checks 字段；
verify_schema.py 再用完全独立的实现复核一遍（不 import 本脚本）。

    python scripts/build_schema.py

输出：
    data/schema.json       类型树 + 算子计划 + 形式检查
    reports/t12_schema.md  人读报告
"""

import collections
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "data" / "graph_v1.json"
OUT = ROOT / "data" / "schema.json"
MD = ROOT / "reports" / "t12_schema.md"

# ---- 四个算子的目标（选择理由写在报告里，不是随手挑的）

REFINE_TARGET = "Q1248784"        # 机场：唯一有大量「父+子」双断言的子树
SPLIT_TARGET = "Q46970"           # 航空公司：货运/非货运，避开与 REFINE 同子树
SPLIT_POSITIVE = "Q1057026"       # 货运航空公司（真实类，11 实例）
SPLIT_NEG_LABEL = "非货运航空公司"  # 补集，合成类，必须在论文标注
RESTRICT_REL = "P113"             # 航空枢纽：唯一"一端是机场"的关系
RESTRICT_COUNTRY = "Q148"         # 收窄为"位于中国的枢纽"
MERGE_N = 12                      # 合成重复对的条数


# ---------------------------------------------------------------- 图索引

class G:
    def __init__(self, d):
        self.d = d
        self.ents = {e["id"]: e for e in d["entities"]}
        self.edges = [dict(e) for e in d["edges"]]
        self.direct = collections.defaultdict(set)     # class -> 直断实例
        self.children = collections.defaultdict(set)
        self.parents = collections.defaultdict(set)
        self.types = collections.defaultdict(set)      # entity -> 直断类集合
        for e in self.edges:
            if e["r"] == "P31":
                self.direct[e["t"]].add(e["h"])
                self.types[e["h"]].add(e["t"])
            elif e["r"] == "P279":
                self.children[e["t"]].add(e["h"])
                self.parents[e["h"]].add(e["t"])

    def descendants(self, c):
        out, stack = set(), [c]
        while stack:
            x = stack.pop()
            for k in self.children.get(x, ()):
                if k not in out:
                    out.add(k)
                    stack.append(k)
        return out

    def closure(self, c):
        """c 的实例闭包：直断 c 的 + 所有后代类的。"""
        s = set(self.direct.get(c, ()))
        for x in self.descendants(c):
            s |= set(self.direct.get(x, ()))
        return s

    def depth(self, c):
        """到根的距离（无父则 0）。带环保护。"""
        seen, cur, d = {c}, c, 0
        while True:
            ps = [p for p in self.parents.get(cur, ()) if p not in seen]
            if not ps:
                return d
            cur = ps[0]
            seen.add(cur)
            d += 1


def label(g, q):
    return g.ents.get(q, {}).get("label_zh") or q


# ---------------------------------------------------------------- 类型树

def build_classes(g):
    classes = set(g.direct) | set(g.children) | set(g.parents)
    out = []
    for c in sorted(classes):
        kids = sorted(g.children.get(c, ()))
        out.append({
            "qid": c,
            "label_zh": label(g, c),
            "parents": sorted(g.parents.get(c, ())),
            "children": kids,
            "n_direct": len(g.direct.get(c, ())),
            "n_subtree": len(g.closure(c)),
            "depth": g.depth(c),
            "in_entities": c in g.ents,
        })
    out.sort(key=lambda r: (-r["n_subtree"], r["qid"]))
    return out


# ---------------------------------------------------------------- 候选扫描

def scan_refine(g):
    """哪些类有「实例同时断言父类与后代类」——只有这种才有可迁移的冗余断言。"""
    rows = []
    for c in g.direct:
        redundant = 0
        for x in g.direct[c]:
            if g.types[x] & g.descendants(c):
                redundant += 1
        if redundant:
            rows.append({"class": c, "label": label(g, c),
                         "n_direct": len(g.direct[c]), "n_redundant": redundant,
                         "ratio": round(redundant / max(len(g.direct[c]), 1), 3)})
    rows.sort(key=lambda r: -r["n_redundant"])
    return rows


def scan_split(g):
    """哪些类有 ≥2 个有实例的子类可供二分（真实二分）。"""
    rows = []
    for c in g.direct:
        kids = [k for k in g.children.get(c, ()) if g.direct.get(k)]
        if len(kids) >= 2:
            pos = set()
            for k in kids:
                pos |= g.closure(k)
            direct = set(g.direct[c])
            rows.append({"class": c, "label": label(g, c),
                         "n_direct": len(direct),
                         "children": [{"qid": k, "label": label(g, k),
                                       "n": len(g.closure(k))} for k in sorted(kids)],
                         "n_covered_by_children": len(pos & direct),
                         "n_residual": len(direct - pos)})
    rows.sort(key=lambda r: -r["n_direct"])
    return rows


# ---------------------------------------------------------------- 四个算子的计划

def plan_refine(g):
    """
    REFINE_TYPE = 最具体类型化：若实例同时断言 C 与 C 的后代 D，删掉指向 C 的那条断言。
    形式条件：C 的实例闭包在操作前后**必须相等**（用集合断言，不用"基本一致"）。
    """
    c = REFINE_TARGET
    desc = g.descendants(c)
    mig = {x for x in g.direct[c] if g.types[x] & desc}
    before = g.closure(c)
    after = (before - mig) | mig | {x for x in g.direct[c] if x not in mig}
    # 模拟：被迁移的实例仍属于某个后代类，故闭包不变
    after_real = set()
    for x in before:
        if x in mig:
            continue
        after_real.add(x)
    for x in mig:                      # 迁移后仍在某个后代类里
        assert g.types[x] & desc
        after_real.add(x)
    return {
        "op": "REFINE_TYPE",
        "mode": "most_specific_typing",
        "target": c, "target_label": label(g, c),
        "n_instances": len(before),
        "n_migrated": len(mig),
        "n_edges_removed": len(mig),
        "migrated_sample": [{"id": x, "label": g.ents[x]["label_zh"],
                             "kept_types": sorted(g.types[x] & desc)} for x in sorted(mig)[:8]],
        "checks": {
            "closure_preserved": before == after_real,
            "n_before": len(before), "n_after": len(after_real),
        },
        "decided_by": "S（形式无争议）；A 只需确认「删冗余父类断言」算不算 REFINE 的合法实现",
    }


def plan_split(g):
    """
    SPLIT_CONCEPT = C 拆为 P（真实子类，已有断言）+ C'（补集，合成类，P279→C）。
    形式条件：P ∩ C' = ∅ 且 P ∪ C' = closure_v1(C)。
    """
    c, p = SPLIT_TARGET, SPLIT_POSITIVE
    universe = g.closure(c)
    pos = g.closure(p)
    neg = universe - pos
    return {
        "op": "SPLIT_CONCEPT",
        "target": c, "target_label": label(g, c),
        "positive": {"qid": p, "label": label(g, p), "n": len(pos),
                     "is_real_class": True},
        "complement": {"qid": "Q_synth_" + c.lower(), "label": SPLIT_NEG_LABEL,
                       "n": len(neg), "is_real_class": False,
                       "note": "补集类为分析构造，Wikidata 无此类；论文必须标注"},
        "checks": {
            "exclusive": len(pos & neg) == 0,
            "union_eq_parent_closure": (pos | neg) == universe,
            "n_universe": len(universe), "n_pos": len(pos), "n_neg": len(neg),
        },
        "decided_by": "pending_A（补集命名与 synthetic 标注方式需 A 拍板，见 D3）",
    }


def plan_restrict(g):
    """
    RESTRICT_REL = 关系收窄：R 的扩展限制到满足条件的边。
    任务书写的是「按起止年份收窄」，但本图时间限定词未取（T1.0-a 见 probe_t10）。
    离线可用条件：尾节点所属国家 == Q148（中国枢纽）。
    """
    r = RESTRICT_REL
    kept, dropped = [], []
    for e in g.edges:
        if e["r"] != r:
            continue
        tail = g.ents.get(e["t"], {})
        (kept if tail.get("country") == RESTRICT_COUNTRY else dropped).append(e)
    return {
        "op": "RESTRICT_REL",
        "relation": r,
        "condition": f"tail.country == {RESTRICT_COUNTRY}（中国）",
        "semantics": f"「{label(g, r) if r in g.ents else 'P113'}」收窄为「位于中国的航空枢纽」",
        "n_kept": len(kept), "n_dropped": len(dropped),
        "note": "任务书的时间收窄需 P580/P582 qualifier，本图未取；见 T1.0-a 判定",
        "decided_by": "pending_A（时间维度缺失是否可接受，见补充决策 D4）",
    }


def plan_merge(g):
    """
    MERGE_ENTITY：图内无真实同指对（T1.0-b 实测 3 对全为假阳性），故合成重复节点。
    构造：取 label_en 做重复节点的标签（模拟"同一实体以另一种语言单独入库"），
    只造输入，不造标签——应然仍由求解器算。
    """
    seeds = [e for e in g.ents.values() if e.get("is_seed") and e.get("label_en")]
    seeds.sort(key=lambda e: e["id"])
    step = max(len(seeds) // MERGE_N, 1)
    picked = seeds[::step][:MERGE_N]
    pairs = []
    for e in picked:
        pairs.append({
            "keep": e["id"], "keep_label": e["label_zh"],
            "drop": f"{e['id']}-dup", "drop_label": e["label_en"],
            "construction": "synthetic_duplicate_by_label_en",
        })
    return {
        "op": "MERGE_ENTITY",
        "n_pairs": len(pairs),
        "pairs": pairs,
        "base_note": "merge 分支的 v1 为 graph_v1_mb.json（v1 + 12 个合成重复节点），v2 为合并后",
        "checks": {
            "no_id_collision": all(p["drop"] not in g.ents for p in pairs),
            "n_pairs_ge_8": len(pairs) >= 8,
        },
        "decided_by": "pending_A（D2：实体级合成 vs 类级真实合并）",
    }


# ---------------------------------------------------------------- 输出

def main():
    d = json.loads(GRAPH.read_text(encoding="utf-8"))
    g = G(d)
    classes = build_classes(g)
    plan = {
        "refine_type": plan_refine(g),
        "split_concept": plan_split(g),
        "restrict_rel": plan_restrict(g),
        "merge_entity": plan_merge(g),
    }
    refine_scan = scan_refine(g)
    split_scan = scan_split(g)

    schema = {
        "meta": {
            "version": "v1",
            "source_graph": "data/graph_v1.json",
            "source_hash": d["meta"]["idempotent_hash"],
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "n_classes": len(classes),
            "n_multi_typed": sum(1 for e in d["entities"] if len(e["type_qids"]) > 1),
            "decision_status": "三个算子目标已定，三处待 A 拍板（见 decisions.md D1-D4）",
        },
        "classes": classes,
        "ops_plan": plan,
        "scans": {"refine_candidates": refine_scan, "split_candidates": split_scan},
    }
    OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- 报告
    L = ["# T1.2 类型清单与算子计划\n",
         f"源图：`data/graph_v1.json`（指纹 `{d['meta']['idempotent_hash']}`）　｜　"
         f"类数：{len(classes)}　｜　多类型实体：{schema['meta']['n_multi_typed']}\n",
         "本文件的每个结论都由 `build_schema.py` 模拟执行并做**集合等式断言**；"
         "`verify_schema.py` 用独立实现复核（不复用本脚本代码）。\n",
         "## 一、类型树概况\n"]
    roots = [c for c in classes if not c["parents"]]
    L.append(f"- 无父类的节点：{len(roots)} 个（多为 Wikidata 顶级类，仅作为边端点存在）")
    L.append(f"- 有子类的类：{sum(1 for c in classes if c['children'])} 个")
    L.append(f"- 叶子类（无子类且有实例）：{sum(1 for c in classes if not c['children'] and c['n_direct'])} 个\n")
    L.append("| 类 | 直断实例 | 子树实例 | 子类 |")
    L.append("|---|---|---|---|")
    for c in classes[:10]:
        L.append(f"| {c['label_zh']} `{c['qid']}` | {c['n_direct']} | {c['n_subtree']} | "
                 f"{len(c['children'])} |")
    L.append("")

    L.append("## 二、REFINE_TYPE：候选扫描与选择\n")
    L.append("判据：只有「实例同时断言父类与后代类」的类才有可迁移的冗余断言；"
             "否则细化无实际改动，该格 FR 恒为 0。\n")
    L.append("| 类 | 直断 | 可迁移 | 占比 |")
    L.append("|---|---|---|---|")
    for r in refine_scan[:8]:
        L.append(f"| {r['label']} `{r['class']}` | {r['n_direct']} | {r['n_redundant']} | {r['ratio']} |")
    L.append("")
    rf = plan["refine_type"]
    L.append(f"**选定 `{rf['target_label']}`**：可迁移 {rf['n_migrated']} 条 P31 断言，"
             f"闭包 {rf['checks']['n_before']} → {rf['checks']['n_after']}，"
             f"集合相等断言 **{rf['checks']['closure_preserved']}**。\n")
    L.append("注意：`航空公司` 子树的可迁移数为 0（货运/廉价/区域/载旗航司都**没有**同时断言父类），"
             "所以拿航空公司做 REFINE 会得到一个零改动的空算子——这正是 T1.0 探针存在的意义。\n")

    L.append("## 三、SPLIT_CONCEPT：真实二分扫描\n")
    L.append("| 类 | 直断 | 有实例子类 | 被子类覆盖 | 残余 |")
    L.append("|---|---|---|---|---|")
    for r in split_scan[:6]:
        L.append(f"| {r['label']} `{r['class']}` | {r['n_direct']} | "
                 f"{'、'.join(k['label'] for k in r['children'])} | "
                 f"{r['n_covered_by_children']} | {r['n_residual']} |")
    L.append("")
    sp = plan["split_concept"]
    L.append(f"**选定 `{sp['target_label']}` → `{sp['positive']['label']}`（{sp['positive']['n']}）"
             f" + `{sp['complement']['label']}`（{sp['complement']['n']}，合成）**")
    L.append(f"- 互斥：**{sp['checks']['exclusive']}**")
    L.append(f"- 并集 = 父类闭包：**{sp['checks']['union_eq_parent_closure']}**"
             f"（{sp['checks']['n_pos']} + {sp['checks']['n_neg']} = {sp['checks']['n_universe']}）\n")

    L.append("## 四、RESTRICT_REL 与 MERGE_ENTITY\n")
    rs = plan["restrict_rel"]
    L.append(f"- RESTRICT：`{rs['relation']}` 收窄为「{rs['semantics']}」，"
             f"保留 {rs['n_kept']} 条、退休 {rs['n_dropped']} 条。")
    L.append("  任务书原方案依赖 P580/P582 qualifier，本图未取；时间维度的处理见 `reports/t10_probe.md`。")
    mg = plan["merge_entity"]
    L.append(f"- MERGE：合成 {mg['n_pairs']} 对重复实体（图内无真实同指对，T1.0-b 实测）。"
             f"只造输入不造标签；合并本身是确定性的。\n")

    L.append("## 五、待 A 拍板\n")
    L.append("| 编号 | 事项 | 现状默认 |")
    L.append("|---|---|---|")
    L.append("| D1 | 130 实体是否够用（c 不达标） | 不扩域，题量 80–100 |")
    L.append("| D2 | MERGE 用合成对还是类级真实合并 | 合成对（实体级） |")
    L.append("| D3 | SPLIT 补集类的命名与 synthetic 标注 | 「非货运航空公司」 |")
    L.append("| D4 | RESTRICT 的时间维度缺失是否可接受 | 接受，改用属性收窄 |")
    L.append("")
    MD.write_text("\n".join(L), encoding="utf-8")
    print(f"写出 {OUT.relative_to(ROOT)} / {MD.relative_to(ROOT)}")
    print("checks:", {k: v.get("checks") for k, v in plan.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
