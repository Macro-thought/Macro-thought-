#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实基线编排器
==============
把 20 个 cell（2 方法 × 5 分支 × 2 版本）跑起来，并在跑之前/之中/之后各做一件事：

    跑之前  写 `_run_config.json`：这一轮用的模型、参数、缓存目录、run_id。没有它，事后
            无法证明"这些行是哪一轮、哪套参数"跑出来的。
    跑之中  每个 cell 一个子进程，cell 内保持串行；cell 之间用线程池并发。子进程隔离的好处
            是：一个 cell 崩了不会带走其它的，且每个文件独立落盘（增量写 + 原子替换）。
    跑之后  扫缓存目录统计 token 用量与成本——缓存记录是唯一带 usage 的地方。

为什么用子进程而不是在线程里直接调 run_graph：
    两个基线有各自的 argparse 与打印，子进程能原样复用它们的 CLI，不改动实验代码；
    而且缓存目录/环境变量按 cell 隔离，避免线程间共享状态。

用法：
    python scripts/run_live.py --pilot --workers 4
    python scripts/run_live.py --full  --workers 4 --resume
"""

import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "baselines" / "out" / "live"
CACHE = ROOT / "baselines" / ".cache_live"
EVENTS = OUT / "_events.jsonl"
RUNCFG = OUT / "_run_config.json"

BRANCHES = ["refine", "restrict", "merge", "split", "all"]
V1_GRAPH = {"merge": "graph_v1_mb.json", "all": "graph_v1_mb.json"}

# 每 100 万 token 的价格（元），仅用于"跑了多少钱"的量级估计，不是账单
PRICE_IN = float(os.environ.get("SCHEMA_CHANGE_PRICE_IN", "2.0"))
PRICE_OUT = float(os.environ.get("SCHEMA_CHANGE_PRICE_OUT", "8.0"))


def load_env():
    env_file = ROOT / "baselines" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def cells():
    """返回 20 个 cell：(method, branch, version, graph, out_name)"""
    out = []
    for branch in BRANCHES:
        v1 = V1_GRAPH.get(branch, "graph_v1.json")
        out.append(("bfs2", branch, "v1", v1))
        out.append(("bfs2", branch, "v2", f"graph_v2_{branch}.json"))
    for branch in BRANCHES:
        # B1 的语料冻结在 canonical v1：v2 输出仍读 v1 图，靠 --version 区分"声称的版本"
        out.append(("b1_text", branch, "v1", "graph_v1.json"))
        out.append(("b1_text", branch, "v2", "graph_v1.json"))
    # 先跑信息量最大的：all/v2（唯一同时含 flip 与 unanswerable 的 cell）
    out.sort(key=lambda c: (0 if (c[0] == "bfs2" and c[1] == "all" and c[2] == "v2") else
                            1 if c[0] == "bfs2" else 2))
    return out


def cmd_for(method, graph, version, branch, questions, out_path, qids, resume):
    script = "baselines/b2_bfs.py" if method == "bfs2" else "baselines/b1_text.py"
    c = [sys.executable, str(ROOT / script),
         "--questions", str(questions), "--graph", str(ROOT / "data" / graph),
         "--version", version, "--branch", branch, "--live",
         "--out", str(out_path), "--cache-dir", str(CACHE)]
    if qids:
        c += ["--qids", qids]
    if resume:
        c += ["--resume"]
    return c


def count_rows(path):
    if not path.exists():
        return 0, 0
    n = bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n += 1
        try:
            r = json.loads(line)
            if (r.get("meta") or {}).get("error"):
                bad += 1
        except Exception:                                          # noqa: BLE001
            bad += 1
    return n, bad


def main():
    ap = argparse.ArgumentParser(description="真实基线编排器")
    ap.add_argument("--pilot", action="store_true", help="19 题冒烟题集")
    ap.add_argument("--full", action="store_true", help="100 题全量题集")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--qids", default=None, help="只跑指定 qid（定向补测用）")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--tag", default=None, help="run_id 后缀")
    args = ap.parse_args()
    if args.pilot == args.full:
        print("必须二选一：--pilot 或 --full")
        return 2

    load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        print("!! 没有 OPENAI_API_KEY（baselines/.env 或环境变量），真实调用会被拒绝")
        return 2

    questions = DATA / ("questions_smoke.json" if args.pilot else "questions_v1.json")
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    run_id = f"live-{datetime.now().strftime('%Y%m%dT%H%M%S')}" + (f"-{args.tag}" if args.tag else "")
    params_effective = {
        "model": os.environ.get("SCHEMA_CHANGE_LLM_MODEL"),
        "temperature": 0, "seed": 42,
        "reasoning_effort": os.environ.get("SCHEMA_CHANGE_REASONING_EFFORT"),
        "timeout_s": int(os.environ.get("SCHEMA_CHANGE_LLM_TIMEOUT", "60")),
    }
    cfg = {
        "run_id": run_id,
        "mode": "pilot" if args.pilot else "full",
        "questions": str(questions.relative_to(ROOT)),
        "qids": args.qids,
        "base_host": os.environ.get("OPENAI_BASE_URL", "").split("//")[-1].split("/")[0],
        "params_effective": params_effective,
        "cache_dir": str(CACHE.relative_to(ROOT)),
        "workers": args.workers,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "cells": [],
    }
    RUNCFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")

    todo = cells()
    print(f"run_id={run_id}  题集={questions.name}  cell={len(todo)}  workers={args.workers}")
    print(f"模型={params_effective['model']}  effort={params_effective['reasoning_effort']}  "
          f"cache={CACHE.relative_to(ROOT)}\n")

    EVENTS.write_text("", encoding="utf-8")
    t_all = time.time()
    results = []

    def run_cell(cell):
        method, branch, version, graph = cell
        name = f"{method}_{branch}_{version}.jsonl"
        out_path = OUT / name
        qids = args.qids
        # 定向补测时不要 resume，否则会跳过已有题而什么都不做
        resume = args.resume and not qids
        t0 = time.time()
        proc = subprocess.run(cmd_for(method, graph, version, branch, questions,
                                      out_path, qids, resume),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        n, bad = count_rows(out_path)
        ev = {"ts": datetime.now().isoformat(timespec="seconds"), "cell": name, "rc": proc.returncode,
              "rows": n, "errors": bad, "sec": round(time.time() - t0, 1)}
        with EVENTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()
        print(f"  [{'ok' if proc.returncode == 0 else 'FAIL'}] {name:<28} rows={n:<4} "
              f"err={bad:<3} {ev['sec']}s  {tail[-1][:70] if tail else ''}")
        return ev

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for ev in ex.map(run_cell, todo):
            results.append(ev)

    # ---- 成本：扫本轮缓存里的 usage
    tin = tout = 0
    n_live = 0
    for f in CACHE.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        if not isinstance(rec, dict) or rec.get("mode") != "live":
            continue
        n_live += 1
        u = rec.get("usage") or {}
        tin += u.get("prompt_tokens") or 0
        tout += u.get("completion_tokens") or 0
    cost = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT

    rows_total = sum(r["rows"] for r in results)
    err_total = sum(r["errors"] for r in results)
    failed = [r["cell"] for r in results if r["rc"] != 0]
    cfg["finished_at"] = datetime.now().isoformat(timespec="seconds")
    cfg["cells"] = results
    cfg["usage"] = {"live_calls_cached": n_live, "prompt_tokens": tin,
                    "completion_tokens": tout, "cost_estimate_cny": round(cost, 3),
                    "price_per_m": {"in": PRICE_IN, "out": PRICE_OUT}}
    RUNCFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n" + "=" * 64)
    print(f"总耗时 {time.time() - t_all:.0f}s   行数 {rows_total}   失败行 {err_total}   失败 cell {len(failed)}")
    print(f"本轮缓存 live 调用 {n_live} 次   token in={tin} out={tout}   估算成本 ¥{cost:.2f}")
    print(f"事件流 {EVENTS.relative_to(ROOT)}   运行配置 {RUNCFG.relative_to(ROOT)}")
    if failed:
        print("失败 cell：" + "、".join(failed))
    print("=" * 64)
    return 0 if not failed and err_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
