#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""metrics/score.py 的冒烟自检：用手写假数据对四个指标各验一个已知答案。

假数据在 `metrics/_fixtures/`，每个用例是一个独立 method，互不干扰：
  m_ffr     10 道 stable，2 道答案变了      → FFR = 2/10 = 0.2
  m_mfr      8 道 flip，  3 道没变           → MFR = 3/8  = 0.375
  m_uar      4 道 unanswerable，2 道 v2 非空 → UAR = 2/4  = 0.5
  m_fr      10 道 mixed（含规范化陷阱），4 道变了 → FR = 4/10 = 0.4
  m_missing  6 道里 1 道缺 v1、1 道缺 v2      → FR 分母只剩 4，缺预测必须被计数

跑法：python metrics/tests_smoke.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import score  # noqa: E402  （脚本只吃文件，不 import baselines/labels/ops）

FIX = HERE / "_fixtures"
QA = FIX / "qa.jsonl"
PRED = FIX / "pred.jsonl"

_passed = 0
_failed: list[str] = []


def check(label: str, hand, got, digits: int = 4) -> None:
    """浮点用手算值 vs 脚本值比较；两边都先 round 到 digits 位。"""
    global _passed
    if isinstance(hand, float) or isinstance(got, float):
        ok = round(float(hand), digits) == round(float(got), digits)
        hs, gs = f"{hand:.{digits}f}", f"{got:.{digits}f}"
    else:
        ok = hand == got
        hs, gs = repr(hand), repr(got)
    if ok:
        _passed += 1
        print(f"  [OK]   {label}: 手算 {hs} | 脚本 {gs}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}: 手算 {hs} | 脚本 {gs}")


def load():
    qa = score.load_qa(QA)
    rows, meta = score.load_preds([PRED])
    table, notes = score.resolve_branches(rows, qa, None)
    results, branches = score.evaluate_all(qa, table)
    return qa, table, results, branches, meta, notes


def section(title: str) -> None:
    print()
    print(f"== {title} ==")


def main() -> int:
    qa, table, results, branches, meta, notes = load()

    section("用例 0：数据装载与分支归属")
    check("qa 题数", 48, len(qa))
    check("只有一个分支", ["refine"], branches)
    check("所有预测都解析到 refine",
          {"refine": 94},
          {"refine": sum(n["branches"].get("refine", 0) for n in notes)})
    check("没有行被丢弃", 0, sum(n["dropped"] for n in notes))

    section("用例 1：FFR（10 道 stable，2 道变）")
    tot = results[("m_ffr", "__total__")]
    check("FFR 分母 n", 10, tot["FFR"]["n"])
    check("FFR 分子 k", 2, tot["FFR"]["k"])
    check("FFR = 2/10", 2 / 10, tot["FFR"]["rate"])

    section("用例 2：MFR（8 道 flip，3 道没变）")
    tot = results[("m_mfr", "__total__")]
    check("MFR 分母 n", 8, tot["MFR"]["n"])
    check("MFR 分子 k（没变的）", 3, tot["MFR"]["k"])
    check("MFR = 3/8", 3 / 8, tot["MFR"]["rate"])

    section("用例 3：UAR（4 道 unanswerable，2 道 v2 仍非空）")
    tot = results[("m_uar", "__total__")]
    check("UAR 分母 n（v2 有预测）", 4, tot["UAR"]["n"])
    check("UAR 分子 k（v2 非空）", 2, tot["UAR"]["k"])
    check("UAR = 2/4", 0.5, tot["UAR"]["rate"])

    section("用例 4：FR + 答案规范化（10 道，4 道真变）")
    tot = results[("m_fr", "__total__")]
    check("FR 分母 n", 10, tot["FR"]["n"])
    check("FR 分子 k", 4, tot["FR"]["k"])
    check("FR = 4/10", 0.4, tot["FR"]["rate"])
    check("其中仅因未作答造成的翻转", 1, tot["FR"]["empty_only"])

    print("  -- 规范化细节（这些对不该被算成翻转）--")
    check('" 188 " == "188"', True, score.canon(" 188 ") == score.canon("188"))
    check('"88.0" == "88"', True, score.canon("88.0") == score.canon("88"))
    check('" ABC " == "abc"', True, score.canon(" ABC ") == score.canon("abc"))
    check('"" == [] （都算未作答）', True,
          score.canon("") is None and score.canon([]) is None)
    check('["b","a"] == ["A","B"]', True,
          score.canon(["b", "a"]) == score.canon(["A", "B"]))
    check('["3"] == "3"', True, score.canon(["3"]) == score.canon("3"))
    check('[1,2] != "1"（形状不同，算变）', True,
          score.canon([1, 2]) != score.canon("1"))
    check('"" != "x"（未作答 vs 有答案，算变）', True,
          score.canon("") != score.canon("x"))

    section("用例 5：缺预测（6 道，1 道缺 v1、1 道缺 v2）")
    tot = results[("m_missing", "__total__")]
    check("FR 分母 n（只剩两版都有的）", 4, tot["FR"]["n"])
    check("FR k = 2", 2, tot["FR"]["k"])
    check("FR = 2/4", 0.5, tot["FR"]["rate"])
    check("缺 v1 计数", 1, tot["FR"]["missing_v1"])
    check("缺 v2 计数", 1, tot["FR"]["missing_v2"])
    # m_missing 只跑了 Q35-Q40 这 6 道，其余 42 道它根本没产出 → 两侧都缺。
    # 这个数必须显式出现，否则"分母变小"会被悄悄忽略。
    check("两侧都缺计数（其余 42 题该方法没跑）", 42, tot["FR"]["missing_both"])
    check("分母 + 各类缺失 == 全部 48 题",
          48, tot["FR"]["n"] + tot["FR"]["missing_v1"]
          + tot["FR"]["missing_v2"] + tot["FR"]["missing_both"])

    section("用例 6：统计工具（对照手算）")
    lo, hi = score.wilson(5, 10)
    check("Wilson(5,10) 下界", 0.2366, lo, digits=3)
    check("Wilson(5,10) 上界", 0.7634, hi, digits=3)
    check("Wilson(0,10) 下界恰为 0", 0.0, score.wilson(0, 10)[0])
    check("Wilson(10,10) 上界恰为 1", 1.0, score.wilson(10, 10)[1])
    check("两比例相等时 p 恰为 1", 1.0, score.two_proportion_p(5, 10, 5, 10))
    # 0/10 vs 5/10：pooled=0.25, se=sqrt(.25*.75*.2)=0.19365, z=-2.5820,
    # 双侧 p = erfc(2.5820/sqrt2) = 0.00982
    check("0/10 vs 5/10 的 p", 0.0098, score.two_proportion_p(0, 10, 5, 10), digits=3)
    lo, hi = score.newcombe_diff_ci(5, 10, 5, 10)
    check("差值 CI 在 Δ=0 时以 0 为中心", 0.0, (lo + hi) / 2, digits=6)
    check("差值 CI 包含 0", True, lo <= 0.0 <= hi)

    section("用例 7：端到端（CLI 写 markdown）")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "m.md"
        js = Path(tmp) / "m.json"
        proc = subprocess.run(
            [sys.executable, str(HERE / "score.py"), "--qa", str(QA),
             "--pred", str(PRED), "--out", str(out), "--json", str(js)],
            capture_output=True, text=True, encoding="utf-8",
        )
        check("退出码", 0, proc.returncode)
        text = out.read_text(encoding="utf-8") if out.exists() else ""
        check("报告已生成", True, bool(text))
        check("含 FFR 章节", True, "2. FFR 误翻转率（核心）" in text)
        check("含 m_ffr 的 FFR 格子", True, "0.200 (n=10)" in text)
        check("含分母脚注", True, "脚注：缺预测明细" in text)
        check("含底噪对照", True, "噪声底噪对照" in text)
        payload = json.loads(js.read_text(encoding="utf-8")) if js.exists() else {}
        check("JSON 里 m_mfr 的 MFR", 0.375,
              payload["groups"]["m_mfr"]["总计"]["MFR"]["rate"])

    section("用例 8：qid 跨分支重复时，预测必须只落到一个分支")
    # 真实数据里 Q001 在 refine 和 split 里各出现一次，而预测行只有
    # meta.graph=graph_v2_split.json。若不按分支配对，一条预测会被算 5 次。
    qa_b = score.load_qa(FIX / "qa_branches.jsonl")
    rows_b, _ = score.load_preds([FIX / "pred_branches.jsonl"])
    table_b, notes_b = score.resolve_branches(rows_b, qa_b, None)
    res_b, br_b = score.evaluate_all(qa_b, table_b)
    check("两个分支都被识别", ["refine", "split"], br_b)
    check("split 的 FR 分母 n=2", 2, res_b[("m_split", "split")]["FR"]["n"])
    check("split 的 FR = 1/2", 0.5, res_b[("m_split", "split")]["FR"]["rate"])
    check("refine 格 n=0（预测没跑 refine）", 0, res_b[("m_split", "refine")]["FR"]["n"])
    check("总计 = split（不重复计数）", 2, res_b[("m_split", "__total__")]["FR"]["n"])
    check("总计的 FR 仍为 1/2", 0.5, res_b[("m_split", "__total__")]["FR"]["rate"])

    print()
    total = _passed + len(_failed)
    if _failed:
        print(f"结果：{_passed}/{total} 通过，失败 {len(_failed)} 项：")
        for name in _failed:
            print(f"  - {name}")
        return 1
    print(f"结果：{_passed}/{total} 全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
