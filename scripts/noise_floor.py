#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
噪声底噪实测（FR 的对照）
=========================
主表的 FR 是「同一分支 v1 vs v2」的答案差，但它没有对照组：模型对**同一个输入**
重复问两次，本身就会有一部分答案抖动。这个抖动就是底噪，不测出来，0.138 这个数
无法判断是「schema 变更导致的」还是「模型本来就不稳」。

设计（用 v1 当反事实）：
    把「未变更的图」跑两遍（独立缓存目录），两遍之间的答案差 = 纯噪声；
    「v1 vs v2」的差 = 噪声 + 变更效应。

为什么只重复 v1 就够：
    v1 是未变更状态，重复它就是主表 FR 的反事实（"如果我跑的是同一张图会怎样"）。
    同时，5 个分支的 v1 只有两张图（refine/restrict/split 用 graph_v1，merge/all 用
    graph_v1_mb），同一票 prompt 会在缓存里自然去重，所以两遍下来只花约 ¥2。
    另外对主表最关键的 all 分支补一组 v2 重复，用来对比"变更后图的噪声"。

用法：
    python scripts/noise_floor.py --reps 2 --workers 6
"""

import argparse
import concurrent.futures as cf
import json
import math
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "baselines" / "out" / "noise"
CACHE_ROOT = ROOT / "baselines" / ".cache_noise"
REPORT = ROOT / "reports" / "noise_floor.md"
DATA = ROOT / "data"

BRANCHES = ["refine", "restrict", "merge", "split", "all"]
V1_GRAPH = {"merge": "graph_v1_mb.json", "all": "graph_v1_mb.json"}

V1_CELLS = [(b, "v1", V1_GRAPH.get(b, "graph_v1.json")) for b in BRANCHES]
# 主表最重要的格：all 分支的 v2（唯一同时含 flip 与 unanswerable 的格）
EXTRA_CELLS = [("all", "v2", "graph_v2_all.json")]


def load_env():
    env_file = ROOT / "baselines" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def run_cell(cell, rep, questions):
    branch, version, graph = cell
    out_dir = OUT_ROOT / f"r{rep}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"bfs2_{branch}_{version}.jsonl"
    cache = CACHE_ROOT / f"r{rep}"
    # 每个 rep 独立缓存：命中上一轮的缓存就等于没测到噪声
    cmd = [sys.executable, str(ROOT / "baselines" / "b2_bfs.py"),
           "--questions", str(questions), "--graph", str(ROOT / "data" / graph),
           "--version", version, "--branch", branch, "--live",
           "--out", str(out), "--cache-dir", str(cache)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=3600)
        rc = proc.returncode
        tail_src = proc.stdout or proc.stderr
    except subprocess.TimeoutExpired:
        rc, tail_src = 124, "TIMEOUT(3600s)"
    rows = 0
    if out.exists():
        rows = sum(1 for l in out.read_text(encoding="utf-8").splitlines() if l.strip())
    tail = (tail_src or "").strip().splitlines()
    print(f"  [{'ok' if rc == 0 else 'FAIL'}] r{rep} "
          f"{branch}/{version:<2} rows={rows:<4} {tail[-1][:60] if tail else ''}", flush=True)
    return rc, rows


def read_rows(path):
    if not path.exists():
        return {}
    return {r["qid"]: r for r in
            (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def compare(rows_a, rows_b, should_of):
    """两遍之间的差异。把「内容翻转」与「拒答抖动」分开：后者是模型改口说不知道，
    不是答案内容变了，混在一起会把"开始拒答"读成"结论翻转"。"""
    n = content = refusal = 0
    stable_n = stable_bad = 0
    for qid, ra in rows_a.items():
        rb = rows_b.get(qid)
        if rb is None:
            continue
        n += 1
        a, b = ra["answer"], rb["answer"]
        if a == b:
            pass
        elif not a or not b:
            refusal += 1
        else:
            content += 1
        if should_of.get(qid) == "stable":
            stable_n += 1
            if a != b:
                stable_bad += 1
    return {"n": n, "flip": content + refusal, "content": content,
            "refusal": refusal, "stable_n": stable_n, "stable_flip": stable_bad}


def main():
    ap = argparse.ArgumentParser(description="噪声底噪实测")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--analyze-only", action="store_true",
                    help="不重跑，只对已有 baselines/out/noise/r*/ 的结果做比较")
    args = ap.parse_args()
    if args.reps < 2:
        raise SystemExit("至少要 2 遍才有噪声可言")

    load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("没有 OPENAI_API_KEY（baselines/.env）")

    questions = DATA / "questions_v1.json"
    qa = [json.loads(l) for l in (DATA / "qa_v1.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    should_of = {r["qid"]: r["should"] for r in qa if r["branch"] == "all"}

    cells = V1_CELLS + EXTRA_CELLS
    if args.analyze_only:
        print("跳过跑批，只做比较（--analyze-only）")
    else:
        print(f"噪声底噪：{len(cells)} 个 cell × {args.reps} 遍，workers={args.workers}")
        jobs = [(c, rep) for rep in range(1, args.reps + 1) for c in cells]
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(lambda j: run_cell(j[0], j[1], questions), jobs))
        if any(rc != 0 for rc, _ in results):
            raise SystemExit("有 cell 失败，先看输出再谈噪声")

    # ---- 逐 cell 比较相邻两遍
    table = []
    for cell in cells:
        branch, version, _g = cell
        a = read_rows(OUT_ROOT / "r1" / f"bfs2_{branch}_{version}.jsonl")
        b = read_rows(OUT_ROOT / "r2" / f"bfs2_{branch}_{version}.jsonl")
        rec = compare(a, b, should_of)
        rec.update({"branch": branch, "version": version})
        table.append(rec)

    # ---- v1 合计（5 个分支的 v1 是同一批题，不能简单相加 n）
    v1_qids = set()
    v1_flip = v1_content = v1_refusal = 0
    v1_stable = v1_stable_bad = 0
    for rec in table:
        if rec["version"] != "v1":
            continue
        a = read_rows(OUT_ROOT / "r1" / f"bfs2_{rec['branch']}_v1.jsonl")
        b = read_rows(OUT_ROOT / "r2" / f"bfs2_{rec['branch']}_v1.jsonl")
        for qid, ra in a.items():
            rb = b.get(qid)
            if rb is None or qid in v1_qids:
                continue
            v1_qids.add(qid)
            x, y = ra["answer"], rb["answer"]
            if x != y:
                v1_flip += 1
                if not x or not y:
                    v1_refusal += 1
                else:
                    v1_content += 1
            if should_of.get(qid) == "stable":
                v1_stable += 1
                if x != y:
                    v1_stable_bad += 1

    lines = []
    add = lines.append
    add("# 噪声底噪实测报告")
    add("")
    add(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    add(f"- 方法：B2（两跳有损）在**未变更的 v1 图**上独立跑 {args.reps} 遍（每遍独立缓存目录），"
        f"比较两遍答案")
    add(f"- 题集：`data/questions_v1.json`（100 题）｜缓存：`baselines/.cache_noise/r*/`（不入库）")
    add("- 含义：这是「同一个输入问两次」的抖动，主表 FR 必须明显高于它，才能说是图变更带来的")
    add("")
    add("## 一、逐格结果")
    add("")
    add("| 分支 | 版本 | n | 翻转 | 其中内容翻转 | 其中拒答抖动 | 噪声 FR |")
    add("|---|---|---|---|---|---|---|")
    for rec in table:
        rate = f"{rec['flip'] / rec['n']:.3f}" if rec["n"] else "—"
        add(f"| {rec['branch']} | {rec['version']} | {rec['n']} | {rec['flip']} | "
            f"{rec['content']} | {rec['refusal']} | **{rate}** |")
    add("")
    n_v1 = len(v1_qids)
    add("## 二、v1 合计（去重后 100 题，不按分支重复计数）")
    add("")
    add(f"- 翻转 **{v1_flip} / {n_v1}** = **{v1_flip / n_v1:.3f}**（内容 {v1_content}，拒答 {v1_refusal}）")
    if v1_stable:
        add(f"- 只在 `should=stable` 的 {v1_stable} 题上：误翻 **{v1_stable_bad} / {v1_stable}** "
            f"= **{v1_stable_bad / v1_stable:.3f}** —— 这是 FFR 的底噪")
    add("")
    add("## 三、与主表对照")
    add("")
    add("| 项 | 值 | 来源 |")
    add("|---|---|---|")
    add(f"| 主表 B2 FR（v1 vs v2） | 0.138（69/500） | `reports/metrics_all_live.md` |")
    add(f"| 主表 B2 FFR | 0.113（49/435） | 同上 |")
    add(f"| 噪声 FR（v1 跑两遍） | **{v1_flip / n_v1:.3f}** | 本报告 |")
    if v1_stable:
        add(f"| 噪声 FFR（v1 跑两遍，stable 子集） | **{v1_stable_bad / v1_stable:.3f}** | 本报告 |")
    add("")
    add("读法：噪声是「同一张图重复问」的抖动。主表 FR 若显著高于噪声，才能归因于图变更；"
        "若两者接近，说明所谓翻转大部分是模型自己的不稳定，主结论不成立。")
    add("")
    # ---- 分层：主表的 v1↔v2 配对里，有一半根本没换 prompt
    live_dir = ROOT / "baselines" / "out" / "live"
    strata = []
    for branch in BRANCHES:
        a = read_rows(live_dir / f"bfs2_{branch}_v1.jsonl")
        b = read_rows(live_dir / f"bfs2_{branch}_v2.jsonl")
        same_q = [q for q in a if q in b and sorted(a[q]["evidence"]) == sorted(b[q]["evidence"])]
        diff_q = [q for q in a if q in b and sorted(a[q]["evidence"]) != sorted(b[q]["evidence"])]

        def flips(qs, a=a, b=b):
            return sum(1 for q in qs if a[q]["answer"] != b[q]["answer"])
        strata.append({"branch": branch, "same_n": len(same_q), "same_flip": flips(same_q),
                       "diff_n": len(diff_q), "diff_flip": flips(diff_q)})
    sn = sum(s["same_n"] for s in strata)
    sf = sum(s["same_flip"] for s in strata)
    dn = sum(s["diff_n"] for s in strata)
    df = sum(s["diff_flip"] for s in strata)
    if sn and dn:
        add("## 四、分层：主表里有一半配对根本没换 prompt")
        add("")
        add("主表的 FR 把两类配对混在一起：**证据（检索到的边）没变**的，prompt 逐字相同 → "
            "缓存命中 → 答案必然相同；**证据变了**的，才是真正的「图变了」。不拆开，"
            "翻转率会被前一类稀释。")
        add("")
        add("| 分支 | 证据未变（题/翻转） | 证据变化（题/翻转） |")
        add("|---|---|---|")
        for s in strata:
            add(f"| {s['branch']} | {s['same_n']} / {s['same_flip']} | "
                f"{s['diff_n']} / {s['diff_flip']} |")
        add(f"| **合计** | **{sn} / {sf}** | **{dn} / {df}** |")
        add("")
        add(f"- 证据未变 **{sf}/{sn} = {sf / sn:.3f}**：这是缓存保证的 0，**不是**模型的稳定性")
        add(f"- 证据变化 **{df}/{dn} = {df / dn:.3f}**：这才是「图变更咬到证据」时的真实翻转率")
        p1, p2 = df / dn, v1_flip / n_v1
        se = math.sqrt(p1 * (1 - p1) / dn + p2 * (1 - p2) / n_v1)
        z = (p1 - p2) / se if se else 0.0
        pv = math.erfc(abs(z) / math.sqrt(2.0))
        add(f"- 与噪声 {p2:.3f} 对照：真实效应高出 **{p1 - p2:+.3f}**"
            f"（近似两比例检验 z={z:.2f}、p={pv:.3f}；**未配对、两边题重叠**，"
            f"这个 p 值偏乐观，只能当量级参考，不能写成「显著高于噪声」）")
        add("")
        add("**这一节改变了主结论的写法**：不能直接说「FR=0.138」，必须写成"
            "「证据变化子集上 FR=X，同一 prompt 重采样的噪声为 Y」。")
        add("")
        add("> 注意：这里只测了 v1 的噪声（反事实），v2 的噪声只在 all 分支各测了一组，见第一节。"
            "两类图的噪声未必相同，论文里应写「底噪在 v1 上实测为 X」。")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (DATA / "noise_floor.json").write_text(json.dumps(
        {"reps": args.reps, "cells": table,
         "v1_total": {"n": n_v1, "flip": v1_flip, "content": v1_content,
                      "refusal": v1_refusal, "stable_n": v1_stable,
                      "stable_flip": v1_stable_bad}}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n写入 {REPORT.relative_to(ROOT)}")
    print(f"v1 噪声 FR = {v1_flip}/{n_v1} = {v1_flip / n_v1:.3f}"
          + (f"；stable 子集误翻 {v1_stable_bad}/{v1_stable}" if v1_stable else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
