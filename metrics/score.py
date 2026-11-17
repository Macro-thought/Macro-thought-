#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扰动实验的"翻转"指标（FR / FFR / MFR / UAR）。

## 为什么是这套指标

本实验不评"答得对不对"，只评"该变的变没变、不该变的变没变"。
同一道题在图的 v1 / v2 上各跑一遍同一方法，只看两份答案是否一致：

  - should=stable       理想：两版答案一致
  - should=flip         理想：两版答案不同
  - should=unanswerable 理想：v2 不给答案

所以不需要 gold 答案，也不该用 accuracy：accuracy 会把"稳定但答错"
和"该翻但没翻"混成一个数，而这恰恰是我们要区分的两件事。

## 为什么分母是"两版都有预测的题"

只有两侧都有观测，才谈得上"变 / 没变"。缺一侧的题既不能算变，也不能算
没变。若把它们塞进分母（算作"没变"），FFR 会被系统性低估；若直接算 0，
则会虚高。因此一律从分母剔除，并单独计数（missing_*）打到脚注上。
缺预测不静默丢弃，是这套表能被审稿人接受的前提。

## 为什么连接键要带 branch

qa 里的 qid 只在**分支内**唯一（真实数据是 Q001-Q019 × 5 个分支）。
而一个方法的预测行通常不带 branch 字段，只带 meta.graph。
若按 qid 裸连接，同一条预测会被同时算到 5 个分支上，分母凭空 ×5。
所以先把每个方法的预测解析到唯一分支（见 resolve_branches），再按分支连接。
解析结果会写进报告，不做隐式假设。

## 为什么只吃文件、不 import 实现

指标一旦复用 baselines / labels / ops 的代码，被测实现里的 bug 会同时污染
"信号"和"尺子"，指标就失去独立性。本脚本只解析 jsonl。

用法：
  python metrics/score.py --qa data/qa_smoke.jsonl \
      --pred baselines/out/bfs2_v1.jsonl --pred baselines/out/bfs2_v2.jsonl \
      [--out reports/metrics.md] [--json out.json] [--branch all]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

# --- 常量 -------------------------------------------------------------

# 95% 双侧正态分位数。硬编码而不用 scipy：标准库优先。
Z95 = 1.959963984540054

# n 小于这个值时格子里打 †，提醒不要解读。
# 取 10 的理由：n=10 时比例的 Wilson 区间宽度约 0.53，任何两个方法在这种
# 样本量下的差距都落在噪声里，报数字只会误导。
MIN_N = 10

METRICS = ("FR", "FFR", "MFR", "UAR")
TOTAL = "__total__"

# 表头的固定分支顺序。数据里出现别的分支会追加在后面（不丢信息）。
CANON_BRANCHES = ("refine", "restrict", "merge", "split", "all")

# 底噪方法：文本基线在 v1/v2 上的答案翻转率，作为"换个图也让答案抖动"的
# 自然噪声水平。没有它，任何 FR 都无法判断是信号还是抖动。
BASELINE_METHOD = "b1_text"

_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


# --- 答案规范化 -------------------------------------------------------

def canon_scalar(value) -> str | None:
    """把单个答案规范成可比较的字符串；空值返回 None（= 未作答）。

    做三件事，每件都只抹平"写法差异"、不抹平"内容差异"：
      1. 去首尾空白、压缩内部连续空白 —— 分词/排版差异不是答案变化；
      2. 大小写不敏感 —— "China" / "china" 是同一个答案；
      3. 数值统一：188 / "188" / "188.0" 归一成 "188"。
         数值这条很关键：模型常把计数写成 188.0，若当成不同答案，
         FR 会凭空抬高一截，那是尺子引入的假信号，不是模型的不稳定。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool 是 int 的子类，先拦掉，避免 True 变成 "1"
        return "true" if value else "false"
    if isinstance(value, float):
        return _canon_number(value)
    if isinstance(value, int):
        return str(value)

    text = " ".join(str(value).split())
    if not text:
        return None
    text = text.lower()
    if _NUM_RE.match(text):
        try:
            return _canon_number(float(text))
        except (ValueError, OverflowError):
            return text
    return text


def _canon_number(num: float) -> str:
    if math.isnan(num):
        return None          # NaN 当"没给出可用答案"
    if math.isinf(num):
        return "inf" if num > 0 else "-inf"
    if float(num).is_integer() and abs(num) < 1e15:
        return str(int(num))
    return repr(num)


def canon(answer):
    """规范化整条答案。列表（枚举题）排序后比较，空值统一成 None。

    列表的处理：
      - 元素逐个规范化后丢弃空元素，全空 → None（未作答）；
      - 排序后再比较，因为枚举题的元素顺序没有语义；
      - 单元素列表等价于该标量（["3"] 与 "3" 是同一个答案，
        否则会把"输出格式不同"误记成翻转）。
    空串 / None / [] / 全空白 → None，一律视为"未作答"，
    避免"没答"被拆成好几种不同的取值。
    """
    if isinstance(answer, (list, tuple)):
        items = [x for x in (canon_scalar(v) for v in answer) if x is not None]
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        return tuple(sorted(items))
    if isinstance(answer, dict):
        # 极少数方法会把答案包成 {"value": ...}，取 value；否则整体当字符串
        if "value" in answer:
            return canon_scalar(answer["value"])
        return canon_scalar(json.dumps(answer, ensure_ascii=False, sort_keys=True))
    return canon_scalar(answer)


def is_answered(canonical) -> bool:
    """规范化后的答案是否算"给出了答案"。None 即未作答。"""
    return canonical is not None


# --- 统计工具（标准库实现） -------------------------------------------

def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """二项比例的 Wilson 得分区间。

    不用 Wald（p ± z*sqrt(p(1-p)/n)）：本实验里比例常接近 0，而且
    n 常常只有十几，Wald 会给出越界的下界甚至宽度为 0 的区间，
    审稿人一眼就能看出问题。Wilson 在小 n 和近 0/1 时都稳定。
    """
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def newcombe_diff_ci(k1: int, n1: int, k2: int, n2: int,
                     z: float = Z95) -> tuple[float, float]:
    """两比例之差的 95% 区间（Newcombe 的 Wilson 混合法，method 10）。

    为什么不直接对差值用 Wilson：Wilson 是单比例区间，差值没有对应的
    Wilson 形式。Newcombe 用两侧各自的 Wilson 端点拼出差值区间，
    小样本下覆盖率接近名义水平，实现也只要标准库。
    """
    if n1 <= 0 or n2 <= 0:
        return (float("nan"), float("nan"))
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    diff = p1 - p2
    lower = diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


def two_proportion_p(k1: int, n1: int, k2: int, n2: int) -> float | None:
    """两比例 z 检验（合并方差、不做连续性校正）的双侧 p 值。

    不做连续性校正的原因：校正会让 p 值偏保守（偏大），对"否定原假设"
    更不利；我们恰恰不想轻易放过差异。这个选择写在 README 里，不是黑箱。
    两边比例完全相等时 z=0，直接返回 1.0（避免 0/0）。
    """
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    var = pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2)
    if var <= 0.0:
        # 两边都是 0 或都是 1：没有方差，也就没有可检验的差异
        return 1.0 if abs(p1 - p2) < 1e-12 else 0.0
    z = (p1 - p2) / math.sqrt(var)
    return math.erfc(abs(z) / math.sqrt(2.0))


# --- 读文件 -----------------------------------------------------------

def load_qa(path: str | Path) -> list[dict]:
    """读 qa.jsonl。只用 qid / branch / should / v1_graph / v2_graph，其余保留。

    唯一性检查用 (branch, qid)：真实数据里 qid 在分支间重复是正常的，
    但同分支内重复一定是数据事故（会让分母翻倍），必须直接报错。
    """
    rows: list[dict] = []
    seen: dict[tuple, int] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"[qa] {path}:{lineno} JSON 解析失败: {exc}") from exc
            qid = row.get("qid")
            branch = row.get("branch")
            if not qid:
                raise SystemExit(f"[qa] {path}:{lineno} 缺少 qid")
            if not branch:
                raise SystemExit(f"[qa] {path}:{lineno} 缺少 branch（qid={qid}）")
            key = (branch, qid)
            if key in seen:
                raise SystemExit(
                    f"[qa] {path}:{lineno} (branch,qid)=({branch},{qid}) 重复，"
                    f"首次出现在第 {seen[key]} 行"
                )
            seen[key] = lineno
            rows.append(row)
    if not rows:
        raise SystemExit(f"[qa] {path} 是空的")
    return rows


def load_preds(paths: list[str]) -> tuple[list[dict], dict]:
    """读一个或多个 pred.jsonl，返回原始行（答案已规范化）与统计信息。

    每行保留 method / qid / version / answer / 显式 branch / meta.graph。
    branch 与 graph 后面要用来把预测挂到唯一分支上。

    重复的判定口径是 (method, branch, qid, version)，**不是** (method,qid,version)：
    qid 在 5 个分支里本来就重复，漏掉 branch 会把「不同分支的正常行」报成
    「重复行」（2026-11-17 pilot 就误报了 304 行），让读者以为数据丢了。
    同分支内同一 (qid,version) 出现两次才是真事故，计数后按最后一条进表。
    """
    rows: list[dict] = []
    dup = 0
    seen: dict[tuple, int] = {}
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"[pred] {path}:{lineno} JSON 解析失败: {exc}") from exc
                qid = raw.get("qid")
                method = raw.get("method")
                version = raw.get("version")
                if not qid or not method or version not in ("v1", "v2"):
                    raise SystemExit(
                        f"[pred] {path}:{lineno} 缺少 qid/method/version，"
                        f"或 version 不是 v1/v2: {raw!r}"
                    )
                meta = raw.get("meta") or {}
                row = {
                    "method": method,
                    "qid": qid,
                    "version": version,
                    "answer": canon(raw.get("answer")),
                    "branch": raw.get("branch"),      # 显式字段优先
                    "graph": meta.get("graph"),       # 退而求其次用图名反推
                }
                key = (method, row["branch"] or row["graph"] or "-", qid, version)
                if key in seen:
                    dup += 1
                seen[key] = len(rows)
                rows.append(row)
    if not rows:
        raise SystemExit("pred 文件里没有可用记录")
    return rows, {"duplicate_rows": dup}


# --- 预测 → 分支的归属解析 --------------------------------------------

def _branch_index(qa_rows: list[dict]) -> dict:
    """建 qa 的索引：分支集合、图 → 分支的映射、qid 是否全局唯一。"""
    by_graph: dict[tuple[str, str], set] = defaultdict(set)
    branches: list[str] = []
    qid_to_branch: dict[str, set] = defaultdict(set)
    for row in qa_rows:
        branch = row["branch"]
        if branch not in branches:
            branches.append(branch)
        if row.get("v1_graph"):
            by_graph[("v1", row["v1_graph"])].add(branch)
        if row.get("v2_graph"):
            by_graph[("v2", row["v2_graph"])].add(branch)
        qid_to_branch[row["qid"]].add(branch)
    return {
        "branches": branches,
        "by_graph": dict(by_graph),
        "qid_to_branch": dict(qid_to_branch),
        "qid_unique": all(len(v) == 1 for v in qid_to_branch.values()),
    }


def _candidates(row: dict, index: dict) -> tuple[set | None, str]:
    """单行的候选分支集合。None 表示这条行没有可用的分支线索。"""
    if row["branch"]:
        return {row["branch"]}, "pred.branch"
    if row["graph"] and (row["version"], row["graph"]) in index["by_graph"]:
        return set(index["by_graph"][(row["version"], row["graph"])]), f"meta.graph={row['graph']}"
    return None, ""


def resolve_branches(rows: list[dict], qa_rows: list[dict],
                     forced_branch: str | None) -> tuple[dict, list[dict]]:
    """把每条预测解析到唯一分支，返回 (table, notes)。

    table 的键是 (method, branch, qid, version)。notes 记录每个方法是如何
    被判定分支的，最终打印到报告里——审稿人应该能复核这个连接，而不是
    相信一个黑箱。

    解析顺序（先强证据后弱证据）：
      1. pred 行的 branch 字段；
      2. 行的 meta.graph 在图 → 分支映射里的唯一候选；
      3. 用同方法 v2 行的图反推（v1 的 graph_v1.json 被 refine/restrict/
         split 共用，单看 v1 无法区分，所以先看 v2）；
      4. 同方法 v1 行的唯一候选；
      5. CLI 的 --branch（用户显式指定，视为可信）；
      6. qa 的 qid 全局唯一时，直接由 qid 反查分支。
    都失败的行不猜：丢弃并计数，在报告里报警。
    """
    index = _branch_index(qa_rows)
    by_method: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_method[row["method"]].append(row)

    table: dict[tuple, object] = {}
    notes: list[dict] = []

    for method in sorted(by_method):
        method_rows = by_method[method]
        cands: dict[int, set | None] = {}
        why: dict[int, str] = {}
        for i, row in enumerate(method_rows):
            c, w = _candidates(row, index)
            cands[i] = c
            why[i] = w

        # 第 3 步：同方法 v2 行的唯一候选（v2 图是分支唯一的）
        v2_singletons = set()
        for i, row in enumerate(method_rows):
            if row["version"] == "v2" and cands[i] and len(cands[i]) == 1:
                v2_singletons |= cands[i]
        v1_singletons = set()
        for i, row in enumerate(method_rows):
            if row["version"] == "v1" and cands[i] and len(cands[i]) == 1:
                v1_singletons |= cands[i]

        choice, source = None, ""
        if len(v2_singletons) == 1:
            choice, source = next(iter(v2_singletons)), "v2 图的唯一候选"
        elif len(v1_singletons) == 1:
            choice, source = next(iter(v1_singletons)), "v1 图的唯一候选"
        elif forced_branch and forced_branch in index["branches"]:
            choice, source = forced_branch, "--branch 指定"
        elif index["qid_unique"]:
            branches_for_qids = {next(iter(index["qid_to_branch"][r["qid"]]))
                                 for r in method_rows if r["qid"] in index["qid_to_branch"]}
            if len(branches_for_qids) == 1:
                choice, source = next(iter(branches_for_qids)), "qa 的 qid 全局唯一"

        resolved: dict[str, int] = defaultdict(int)
        dropped = 0
        conflicts = 0
        for i, row in enumerate(method_rows):
            c = cands[i]
            branch = None
            if c and len(c) == 1:
                branch = next(iter(c))
                if choice and branch != choice:
                    conflicts += 1
                    branch = choice      # 方法级证据优先，保证一对 v1/v2 落在同一分支
            elif choice:
                if c and choice not in c:
                    dropped += 1
                    continue
                branch = choice
            if branch is None:
                dropped += 1
                continue
            key = (method, branch, row["qid"], row["version"])
            table[key] = row["answer"]
            resolved[branch] += 1

        notes.append({
            "method": method,
            "branches": dict(resolved),
            "source": source or ("未解析" if dropped else "无"),
            "dropped": dropped,
            "conflicts": conflicts,
        })

    return table, notes


# --- 单个 (method, branch) 格子的计算 ---------------------------------

def _blank() -> dict:
    return {"k": 0, "n": 0, "missing_v1": 0, "missing_v2": 0,
            "missing_both": 0, "empty_only": 0, "unknown_should": 0}


def evaluate_group(qa_rows: list[dict], preds: dict, method: str) -> dict:
    """算一个 method 在一组题上的四个指标。

    preds 的键是 (qid, version)，作用域已限定在某个 method × branch 内。
    每个指标的分母（写死在这里，也写在 README 里）：

      FR  = 分母: 该组内 v1 和 v2 都有预测的题
            分子: 两版规范化答案不相等
      FFR = 分母: 该组内 should=stable 且两版都有预测的题
            分子: 答案发生变化（核心指标：改图不该让稳定题翻）
      MFR = 分母: 该组内 should=flip 且两版都有预测的题
            分子: 答案没有变化（该翻没翻）
      UAR = 分母: 该组内 should=unanswerable 且 v2 有预测的题
            分子: v2 仍给出非空答案

    "有预测"指有这一行记录；记录里的 answer 为空串/[]/null 算"未作答"，
    仍然参与比较（于是"有答案 → 未作答"会被记为一次翻转）。
    这样处理的原因：对同一方法而言，"这次拒答了"本身就是行为变化，
    不能被当作缺失。真正的缺失只有"连行都没有"。
    """
    fr, ffr, mfr, uar = _blank(), _blank(), _blank(), _blank()

    for row in qa_rows:
        qid = row["qid"]
        should = row.get("should")

        key1 = (qid, "v1")
        key2 = (qid, "v2")
        has1 = key1 in preds
        has2 = key2 in preds
        a1 = preds.get(key1)
        a2 = preds.get(key2)

        both = has1 and has2
        changed = bool(both and a1 != a2)
        # 仅因一侧未作答造成的"翻转"：这类翻转对"模型是否拒答"极敏感，
        # 单独计数放进脚注，避免它被当成内容层面的结论。
        empty_only = bool(changed and (not is_answered(a1) or not is_answered(a2)))

        # --- FR：全组无条件（不按 should 筛） ---
        if both:
            fr["n"] += 1
            if changed:
                fr["k"] += 1
                if empty_only:
                    fr["empty_only"] += 1
        elif not has1 and not has2:
            fr["missing_both"] += 1
        elif not has1:
            fr["missing_v1"] += 1
        else:
            fr["missing_v2"] += 1

        if should == "stable":
            if both:
                ffr["n"] += 1
                if changed:
                    ffr["k"] += 1
                    if empty_only:
                        ffr["empty_only"] += 1
            elif not has1 and not has2:
                ffr["missing_both"] += 1
            elif not has1:
                ffr["missing_v1"] += 1
            else:
                ffr["missing_v2"] += 1

        elif should == "flip":
            if both:
                mfr["n"] += 1
                if not changed:
                    mfr["k"] += 1
            elif not has1 and not has2:
                mfr["missing_both"] += 1
            elif not has1:
                mfr["missing_v1"] += 1
            else:
                mfr["missing_v2"] += 1

        elif should == "unanswerable":
            # 只看 v2：v1 本来就该有答案，不参与。
            if has2:
                uar["n"] += 1
                if is_answered(a2):
                    uar["k"] += 1
            else:
                uar["missing_v2"] += 1

        else:
            # 未知标签：不猜。计数后报警，否则 FFR/MFR 的分母会莫名变小。
            fr["unknown_should"] += 1

    out = {"FR": fr, "FFR": ffr, "MFR": mfr, "UAR": uar}
    for rec in out.values():
        rec["rate"] = (rec["k"] / rec["n"]) if rec["n"] else None
    return out


def merge_records(records: list[dict]) -> dict:
    """把多个分支的记录相加成总计。

    相加而不是重算：分支之间用的是不同的 v2 图，跨分支不能按 qid 重新配对
    （同 qid 在不同分支是两个独立实验）。所以总计 = 各分支分子分母之和，
    missing 也一并累加 —— 这样"只跑了 1 个分支、另外 4 个分支全缺"的事实
    会如实出现在总计的脚注里，而不是被悄悄藏掉。
    """
    out = _blank()
    for rec in records:
        for key in out:
            out[key] += rec.get(key, 0)
    out["rate"] = (out["k"] / out["n"]) if out["n"] else None
    return out


# --- 整体评估 ---------------------------------------------------------

def evaluate_all(qa_rows: list[dict], table: dict,
                 branch_filter: str | None = None) -> tuple[dict, list[str]]:
    """按 method × branch 汇总，并给出每个 method 的总计。

    返回 (results, branches)。results[(method, branch)] = {指标: 记录}。
    """
    rows = qa_rows
    if branch_filter:
        rows = [r for r in rows if r.get("branch") == branch_filter]
        if not rows:
            raise SystemExit(f"branch={branch_filter} 没有题，检查 --branch 拼写或数据")

    present = {r["branch"] for r in rows}
    branches = [b for b in CANON_BRANCHES if b in present]
    branches += sorted(present - set(CANON_BRANCHES))

    methods = sorted({m for (m, _b, _q, _v) in table})
    # 基线排最前，其余按字母序：读表时先看到噪声水平。
    methods.sort(key=lambda m: (m != BASELINE_METHOD, m))

    results: dict[tuple[str, str], dict] = {}
    for method in methods:
        per_branch = []
        for branch in branches:
            sub_qa = [r for r in rows if r["branch"] == branch]
            sub_preds = {
                (qid, ver): ans
                for (m, b, qid, ver), ans in table.items()
                if m == method and b == branch
            }
            rec = evaluate_group(sub_qa, sub_preds, method)
            results[(method, branch)] = rec
            per_branch.append(rec)
        results[(method, TOTAL)] = {
            name: merge_records([rec[name] for rec in per_branch])
            for name in METRICS
        }

    return results, branches


# --- 渲染 -------------------------------------------------------------

def _cell(rec: dict) -> str:
    """一个格子：值 + 分母。n=0 时不写数字，避免"0.000"被当成结论。"""
    if not rec["n"]:
        return "— (n=0)"
    text = f"{rec['rate']:.3f} (n={rec['n']})"
    if rec["n"] < MIN_N:
        text += " †"
    return text


def _missing_line(method: str, res: dict) -> str:
    parts = []
    for name in METRICS:
        rec = res[name]
        if rec["n"] == 0:
            # 分母为 0 且整组都缺 = 该方法在这批题上根本没产出，比"缺几道"
            # 更严重，单独标出来，不混进缺 v1/缺 v2 的计数。
            had = rec["missing_v1"] + rec["missing_v2"] + rec["missing_both"]
            parts.append(f"{name}:" + ("全缺" if had else "无样本"))
            continue
        bits = []
        if rec["missing_v1"]:
            bits.append(f"缺v1={rec['missing_v1']}")
        if rec["missing_v2"]:
            bits.append(f"缺v2={rec['missing_v2']}")
        if rec["missing_both"]:
            bits.append(f"两侧缺={rec['missing_both']}")
        # 分子里有多少只是"一侧从有答案变成没答案"：FFR 上这点尤其要标，
        # 否则拒答抖动会被读成"图结构让答案变了"。
        if rec.get("empty_only"):
            bits.append(f"其中空答翻转={rec['empty_only']}")
        parts.append(f"{name}:" + ("/".join(bits) if bits else "无缺失"))
    return f"- `{method}` — " + "；".join(parts)


def render_markdown(results: dict, branches: list[str], qa_rows: list[dict],
                    pred_meta: dict, notes: list[dict], args) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    methods = sorted({m for (m, _b) in results})
    methods.sort(key=lambda m: (m != BASELINE_METHOD, m))

    lines: list[str] = []
    add = lines.append

    add("# 翻转指标报告")
    add("")
    add(f"- 生成时间：{now}")
    add(f"- qa：`{args.qa}`（{len(qa_rows)} 题，"
        f"{len({r['qid'] for r in qa_rows})} 个不同 qid，qid 在分支内唯一）")
    add("- pred：" + "、".join(f"`{p}`" for p in args.pred))
    add(f"- branch 过滤：`{args.branch}`")
    add(f"- 方法：{', '.join(methods) if methods else '（无）'}")
    if pred_meta.get("duplicate_rows"):
        add(f"- ⚠ 预测文件里有 {pred_meta['duplicate_rows']} 行同分支内重复的 "
            f"(method,branch,qid,version)，配对时按最后一条取值")
    add("")
    add("> 格子格式 `指标值 (n=分母)`。n 是该格有效样本数；`—` 表示 n=0，"
        "此时数值无意义，不要解读。")
    add(f"> `†` 表示 n < {MIN_N}：样本太少，区间宽度足以覆盖任何真实差异，只作参考。")
    add("")

    # --- 预测与分支的归属（连接过程要可复核） ---
    add("## 0. 预测的分支归属")
    add("")
    add("一个方法通常只在一张 v2 图上跑过，而 qa 的 qid 在各分支里重复，"
        "所以先把预测解析到唯一分支再配对。解析依据如下：")
    add("")
    add("| method | 落入分支（行数） | 解析依据 | 丢弃行 | 图名冲突 |")
    add("|---|---|---|---|---|")
    for note in notes:
        b = "、".join(f"{k}={v}" for k, v in sorted(note["branches"].items())) or "—"
        add(f"| `{note['method']}` | {b} | {note['source']} | "
            f"{note['dropped']} | {note['conflicts']} |")
    add("")
    dropped_total = sum(n["dropped"] for n in notes)
    if dropped_total:
        add(f"> ⚠ 有 {dropped_total} 行预测无法确定所属分支，已丢弃（未计入任何指标）。"
            f"请给 pred 行补 `branch` 字段，或用 `--branch` 指定。")
        add("")

    titles = {
        "FR": ("1. FR 答案翻转率", "两版都有预测的题里，答案不同的比例。整体抖动水平，不是好坏指标。"),
        "FFR": ("2. FFR 误翻转率（核心）",
                "should=stable 且两版都有预测的题里，答案变了的比例。越低越好："
                "改图不该让本该稳定的题翻。"),
        "MFR": ("3. MFR 漏翻转率",
                "should=flip 且两版都有预测的题里，答案没变的比例。越低越好："
                "该翻的没翻，说明扰动没被捕捉到。"),
        "UAR": ("4. UAR 不可答误答率",
                "should=unanswerable 且 v2 有预测的题里，v2 仍给出非空答案的比例。越低越好。"),
    }

    header = "| method | " + " | ".join(branches + ["总计"]) + " |"
    sep = "|" + "---|" * (len(branches) + 2)

    for name in METRICS:
        title, desc = titles[name]
        add(f"## {title}")
        add("")
        add(desc)
        add("")
        add(header)
        add(sep)
        for method in methods:
            cells = [_cell(results[(method, b)][name]) for b in branches]
            cells.append(_cell(results[(method, TOTAL)][name]))
            add(f"| `{method}` | " + " | ".join(cells) + " |")
        add("")

    # --- 噪声底噪对照 ---
    add("## 5. 噪声底噪对照（FR vs `b1_text`）")
    add("")
    add("把文本基线在 v1/v2 上的 FR 当底噪：不依赖图结构的方法，单换一张图也会"
        "让一部分答案抖动。只有明显高于底噪的 FR 才算图结构带来的信号。")
    add("")
    base = results.get((BASELINE_METHOD, TOTAL))
    if base is None or not base["FR"]["n"]:
        add(f"> 预测里没有可用的 `{BASELINE_METHOD}`（缺失或该分支没有题），"
            f"本节跳过，未做底噪对照。")
        add("")
    else:
        b = base["FR"]
        add(f"底噪：`{BASELINE_METHOD}` FR = {b['rate']:.3f} "
            f"(n={b['n']}，{b['k']}/{b['n']})")
        if b["n"] < MIN_N:
            add("")
            add(f"> ⚠ 底噪自身 n={b['n']} < {MIN_N}，这个底噪不可靠，下面的差值仅供参考。")
        add("")
        add("| method | FR (n) | 底噪 FR (n) | Δ = FR − 底噪 | 95% CI（Newcombe） | z 检验 p | 判定 |")
        add("|---|---|---|---|---|---|---|")
        for method in methods:
            if method == BASELINE_METHOD:
                continue
            cur = results[(method, TOTAL)]["FR"]
            if not cur["n"]:
                add(f"| `{method}` | — (n=0) | {b['rate']:.3f} (n={b['n']}) "
                    f"| — | — | — | 无样本 |")
                continue
            diff = cur["rate"] - b["rate"]
            lo, hi = newcombe_diff_ci(cur["k"], cur["n"], b["k"], b["n"])
            p = two_proportion_p(cur["k"], cur["n"], b["k"], b["n"])
            tiny = cur["n"] < MIN_N or b["n"] < MIN_N
            if p is None:
                verdict, p_txt = "样本不足", "—"
            else:
                verdict = ("差异显著" if p < 0.05 else "无显著差异") + ("（n 太小）" if tiny else "")
                p_txt = f"{p:.4f}" if p >= 1e-4 else "<0.0001"
            ci_txt = "—" if math.isnan(lo) else f"[{lo:+.3f}, {hi:+.3f}]"
            add(f"| `{method}` | {cur['rate']:.3f} (n={cur['n']}) | "
                f"{b['rate']:.3f} (n={b['n']}) | {diff:+.3f} | {ci_txt} | {p_txt} | {verdict} |")
        add("")
        add("注：区间是**差值**的区间（Newcombe 混合法），不是两个单侧 Wilson 区间；"
            "p 值来自未做连续性校正的两比例 z 检验。区间跨 0 且 p≥0.05 时，"
            "只能说「没看到差异」，不能说「两者一样」。")
        add("")

    # --- 脚注：缺预测与空答 ---
    add("## 脚注：缺预测明细（不静默丢弃）")
    add("")
    add("缺预测的题已从对应指标的分母剔除，下面是剔除量（按 method 总计）。"
        "若某格 missing 占比很高，该格的指标实际只代表一小撮题，不能外推。")
    add("")
    for method in methods:
        add(_missing_line(method, results[(method, TOTAL)]))
    add("")

    empties = []
    for method in methods:
        rec = results[(method, TOTAL)]["FR"]
        if rec["empty_only"]:
            empties.append(f"`{method}` {rec['empty_only']}/{rec['k']}")
    if empties:
        add("空答提示：以下方法的 FR 里，有翻转是由「一侧未作答（空串/[]）」造成的，"
            "不是内容层面的变化：" + "、".join(empties) + "。")
        add("")

    add("---")
    add("")
    add("指标定义与「为什么不用 accuracy」见 `metrics/README.md`；"
        "自检见 `python metrics/tests_smoke.py`。")
    return "\n".join(lines) + "\n"


# --- CLI --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="计算 FR / FFR / MFR / UAR（按 method × branch 分组，每格带分母 n）"
    )
    p.add_argument("--qa", required=True, help="qa.jsonl 路径")
    p.add_argument("--pred", required=True, action="append", metavar="PRED",
                   help="pred.jsonl 路径，可重复给多个；也可以一个文件里混多个 method")
    p.add_argument("--out", default="reports/metrics.md",
                   help="markdown 输出路径，给 - 表示打到 stdout（默认 reports/metrics.md）")
    p.add_argument("--json", dest="json_out", default=None, help="把指标写成 JSON")
    p.add_argument("--branch", default="all",
                   help="只统计某个分支（all/refine/restrict/merge/split），默认 all")
    return p


def results_to_json(results: dict, qa_rows: list[dict], pred_meta: dict,
                    notes: list[dict], args) -> dict:
    payload = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "inputs": {"qa": args.qa, "pred": args.pred, "branch": args.branch,
                   "n_questions": len(qa_rows), **pred_meta},
        "min_n": MIN_N,
        "baseline": BASELINE_METHOD,
        "branch_resolution": notes,
        "groups": {},
    }
    for (method, branch), res in results.items():
        key = "总计" if branch == TOTAL else branch
        payload["groups"].setdefault(method, {})[key] = {
            name: {"k": res[name]["k"], "n": res[name]["n"],
                   "rate": res[name]["rate"],
                   "missing": {k: res[name][k] for k in
                               ("missing_v1", "missing_v2", "missing_both")},
                   "empty_only": res[name]["empty_only"]}
            for name in METRICS
        }
    base = results.get((BASELINE_METHOD, TOTAL))
    if base and base["FR"]["n"]:
        b = base["FR"]
        payload["noise"] = {"baseline": BASELINE_METHOD,
                            "fr": b["rate"], "n": b["n"], "comparisons": {}}
        for (method, branch), res in results.items():
            if branch != TOTAL or method == BASELINE_METHOD:
                continue
            cur = res["FR"]
            if not cur["n"]:
                continue
            payload["noise"]["comparisons"][method] = {
                "fr": cur["rate"], "n": cur["n"],
                "delta": cur["rate"] - b["rate"],
                "ci95": list(newcombe_diff_ci(cur["k"], cur["n"], b["k"], b["n"])),
                "p_value": two_proportion_p(cur["k"], cur["n"], b["k"], b["n"]),
            }
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    for path in [args.qa] + args.pred:
        if not Path(path).exists():
            raise SystemExit(f"找不到文件: {path}")

    qa_rows = load_qa(args.qa)
    pred_rows, pred_meta = load_preds(args.pred)

    branch_filter = None if args.branch in ("all", "", None) else args.branch

    table, notes = resolve_branches(pred_rows, qa_rows, branch_filter)
    if not table:
        raise SystemExit(
            "没有任何预测能确定所属分支。请给 pred 行加 branch 字段，"
            "或用 --branch 指定这批预测对应的分支。"
        )

    # 方法解析到的分支不在当前过滤范围内时，表格会全空，必须明确提醒
    visible = {r["branch"] for r in qa_rows
               if branch_filter is None or r["branch"] == branch_filter}
    for note in notes:
        for b, cnt in note["branches"].items():
            if b not in visible:
                print(f"[warn] `{note['method']}` 的 {cnt} 行预测属于分支 `{b}`，"
                      f"被 --branch={args.branch} 过滤掉了", file=sys.stderr)

    results, branches = evaluate_all(qa_rows, table, branch_filter)

    unknown = sum((r["FR"].get("unknown_should") or 0) for r in results.values())
    if unknown:
        print(f"[warn] 有 {unknown} 条题的 should 不是 "
              f"stable/flip/unanswerable，已排除在 FFR/MFR/UAR 之外", file=sys.stderr)

    md = render_markdown(results, branches, qa_rows, pred_meta, notes, args)
    if args.out == "-":
        sys.stdout.write(md)
    else:
        out_path = Path(args.out)
        if out_path.parent and not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        methods = sorted({m for (m, _b) in results})
        print(f"已写入 {out_path}（{len(methods)} 个方法 × {len(branches)} 个分支）")
        for method in methods:
            tot = results[(method, TOTAL)]
            frag = []
            for name in METRICS:
                rec = tot[name]
                value = "—" if not rec["n"] else f"{rec['rate']:.3f}"
                frag.append(f"{name}={value}(n={rec['n']})")
            print(f"  {method:<12} " + "  ".join(frag))

    if args.json_out:
        payload = results_to_json(results, qa_rows, pred_meta, notes, args)
        jp = Path(args.json_out)
        if jp.parent and not jp.parent.exists():
            jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.out != "-":
            print(f"已写入 {jp}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
