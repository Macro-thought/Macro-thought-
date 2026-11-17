#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.5 应然矩阵：先验 vs 实测
===========================
只做三件事：读 `data/qa_v1.jsonl` 聚合 20 格（5 分支 × 4 答形）、读先验、对照。

**纪律（decisions.md D5）**：先验必须由 A 填写并标 `confirmed_by`，否则本脚本
只输出实测、不输出「一致/不一致」的判断——因为先验若是我事后补的，
对照就成了自证。脚本用 `--force-compare` 也绕不过这条：它只会打印警告。

格子的先验写成三类断言（可判真假，不写具体数字，因为数字要跑完才知道）：
    "all_stable"   该格应全部 stable
    "some_flip"    该格应出现翻转（数量不定），但仍有 stable
    "mixed"        该格应同时出现 stable 与 unanswerable
    "unknown"      不预设

用法：
    python scripts/t15_matrix.py                 # 实测 + 对照（先验未确认时只给实测）
    python scripts/t15_matrix.py --draft         # 用 S 的草稿先验做「预演」，输出标 DRAFT
"""

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
QA = DATA / "qa_v1.jsonl"
PRIOR = DATA / "prior_20grid.json"          # A 填的正式先验
DRAFT = DATA / "prior_draft_by_S.json"      # S 的草稿，不参与正式对照
OUT = ROOT / "reports" / "t15_matrix.md"

BRANCHES = ["refine", "restrict", "merge", "split", "all"]
SHAPES = ["count", "set", "bool", "hop2"]


def load_qa():
    rows = [json.loads(l) for l in QA.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows


def aggregate(rows):
    m = collections.defaultdict(collections.Counter)
    for r in rows:
        m[(r["branch"], r["shape"])][r["should"]] += 1
    return m


def judge(prior, cell):
    """把先验断言变成可判真假的三值：True / False / None（无法判）。"""
    s, f, u = cell["stable"], cell["flip"], cell["unanswerable"]
    if prior == "all_stable":
        return f == 0 and u == 0
    if prior == "some_flip":
        return f > 0 and s > 0
    if prior == "mixed":
        return s > 0 and u > 0
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true", help="用草稿先验预演（输出标 DRAFT）")
    args = ap.parse_args()

    rows = load_qa()
    m = aggregate(rows)

    prior_doc, is_draft = None, False
    if args.draft and DRAFT.exists():
        prior_doc, is_draft = json.loads(DRAFT.read_text(encoding="utf-8")), True
    elif PRIOR.exists():
        prior_doc = json.loads(PRIOR.read_text(encoding="utf-8"))

    confirmed = bool(prior_doc and prior_doc.get("meta", {}).get("confirmed_by"))
    cells = (prior_doc or {}).get("cells", {})

    L = ["# T1.5 应然矩阵：先验 vs 实测\n",
         f"数据：`data/qa_v1.jsonl`（{len(rows)} 行 = 100 题 × 5 分支）　｜　"
         f"生成：`scripts/t15_matrix.py`\n"]
    if is_draft:
        L.append("> **DRAFT：本表用的是 S 的草稿先验，不是 A 的正式先验。"
                 "草稿只用于预演脚本、检查格子是否可判，不构成 T1.5 结论。**\n")
    elif not confirmed:
        L.append("> **先验未确认：只输出实测，不输出「一致/不一致」。**"
                 "请 A 填 `data/prior_20grid.json` 并在 `meta.confirmed_by` 签名"
                 "（见 decisions.md D5）。\n")

    L.append("## 实测（stable / flip / unanswerable）\n")
    head = "| 分支 | " + " | ".join(SHAPES) + " |"
    L.append(head)
    L.append("|---" * (len(SHAPES) + 1) + "|")
    for b in BRANCHES:
        L.append(f"| {b} | " + " | ".join(
            f"{m[(b, s)]['stable']}/{m[(b, s)]['flip']}/{m[(b, s)]['unanswerable']}"
            for s in SHAPES) + " |")
    L.append("")

    if cells and (confirmed or is_draft):
        L.append("## 对照\n")
        L.append("| 分支 | 答形 | 先验 | 实测 s/f/u | 判定 |")
        L.append("|---|---|---|---|---|")
        bad = 0
        for b in BRANCHES:
            for s in SHAPES:
                p = cells.get(f"{b}×{s}") or cells.get(f"{b}/{s}")
                if not p:
                    continue
                cell = m[(b, s)]
                ok = judge(p.get("expect"), cell)
                mark = "—" if ok is None else ("一致" if ok else "**不一致**")
                if ok is False:
                    bad += 1
                L.append(f"| {b} | {s} | {p.get('expect')} | "
                         f"{cell['stable']}/{cell['flip']}/{cell['unanswerable']} | {mark} |")
        L.append("")
        L.append(f"不一致格数：{bad}。每一条不一致都必须进 `decisions.md` 的 unexplained 列表，"
                 "**不许现场改先验或改 solver**。\n")
    else:
        L.append("## 对照\n")
        L.append("先验未填或未确认，跳过对照。填法见 `data/prior_20grid.template.json`。\n")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[-14:] if cells else L[-8:]))
    print(f"写出 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
