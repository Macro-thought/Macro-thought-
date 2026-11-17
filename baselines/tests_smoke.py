#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冒烟测试：stub 模式下 B1/B2 端到端跑通
=====================================
跑 2 方法 × 2 图 × 19 题 = 76 行，断言四件事：
  1. 行数、字段、每格 19 题（输出格式冻结，组内 SCHEMA.md 不允许改字段名）；
  2. B2 的 evidence ≤ 20 条，且 id 都在该版本的当前图里（退休边不许混进来）；
  3. B1 两次运行**逐字节相同** —— 用两个全新的空缓存目录各跑一次，
     这样"相同"不能是靠缓存命中糊弄过去的；
  4. B1 的 v1 行与 v2 行除 version/graph 外完全相同 —— 这是负控的定义性性质，
     比"两次跑一样"更强：它说明语料真的没随版本变。

不联网、不需要 key。用法：python baselines/tests_smoke.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import b1_text          # noqa: E402
import b2_bfs           # noqa: E402
import graph_access as ga   # noqa: E402
import llm              # noqa: E402

FIELDS = ["qid", "method", "version", "branch", "answer", "evidence", "raw", "meta"]
GRAPHS = {
    "v1": ROOT / "data" / "graph_v1.json",
    "v2": ROOT / "data" / "graph_v2_split.json",
}
OUT = HERE / "out"


def _read_rows(path):
    return [json.loads(l) for l in Path(path).read_text("utf-8").splitlines() if l.strip()]


def _check_schema(rows, method, version, qs):
    assert len(rows) == len(qs), f"{method}/{version}: 行数 {len(rows)} != {len(qs)}"
    assert [r["qid"] for r in rows] == [q["qid"] for q in qs], f"{method}/{version}: qid 顺序/集合不符"
    for r in rows:
        assert list(r.keys()) == FIELDS, f"{method}/{version}: 字段名或顺序被改动 {list(r.keys())}"
        assert r["method"] == method and r["version"] == version, f"{r['qid']}: method/version 不符"
        assert isinstance(r["answer"], str) and isinstance(r["evidence"], list) and isinstance(r["raw"], str)
        assert all(isinstance(x, str) and x.startswith("e:") for x in r["evidence"])
        m = r["meta"]
        assert m["temperature"] == 0 and m["seed"] == 42, f"{r['qid']}: 冻结项被改动 {m}"
        assert m["graph"] and m["template"], f"{r['qid']}: meta 缺 graph/template"


def main() -> int:
    qs = json.loads((ROOT / "data" / "questions_smoke.json").read_text("utf-8"))["questions"]
    OUT.mkdir(parents=True, exist_ok=True)
    graphs = {k: ga.Graph.load(v) for k, v in GRAPHS.items()}

    cells = {}
    for method, fn in (("b1_text", b1_text.run_graph), ("bfs2", b2_bfs.run_graph)):
        for ver, gp in GRAPHS.items():
            out = OUT / f"{method}_{ver}.jsonl"
            fn(qs, gp, out, stub=True)
            rows = _read_rows(out)
            _check_schema(rows, method, ver, qs)
            cells[(method, ver)] = rows

    total = sum(len(v) for v in cells.values())
    assert total == 19 * 2 * 2, f"总行数 {total} != 76"

    # ---- B2：evidence ≤ 20，且只能引用当前图的边；退休边绝不允许出现
    retired = {e["id"] for e in graphs["v2"].retired}
    for ver in GRAPHS:
        for r in cells[("bfs2", ver)]:
            assert len(r["evidence"]) <= b2_bfs.MAX_EDGES, f"{r['qid']}/{ver}: evidence 超 20 条"
            for eid in r["evidence"]:
                assert graphs[ver].has_edge(eid), f"{r['qid']}/{ver}: evidence {eid} 不在当前图"
                if ver == "v2":  # v1 图没有 retired_edges 字段，这条只对 v2 有意义
                    assert eid not in retired, f"{r['qid']}/{ver}: evidence {eid} 是 v2 的退休边"
        # P279 不进子图（硬约束 4）
        for r in cells[("bfs2", ver)]:
            for eid in r["evidence"]:
                e = next(x for x in graphs[ver].edges if x["id"] == eid)
                assert e["r"] not in b2_bfs.FORBIDDEN_RELS, f"{r['qid']}/{ver}: 子图混入 P279"

    # ---- B1：两次冷启动逐字节相同
    tmp = Path(tempfile.mkdtemp(prefix="b1det_"))
    try:
        a, b = tmp / "a.jsonl", tmp / "b.jsonl"
        b1_text.run_graph(qs, GRAPHS["v1"], a, stub=True, cache_dir=tmp / "cache_a")
        b1_text.run_graph(qs, GRAPHS["v1"], b, stub=True, cache_dir=tmp / "cache_b")
        assert a.read_bytes() == b.read_bytes(), "B1 两次运行不逐字节相同（temperature=0 的意义被破坏）"
        # 再跑一次走缓存（新目录就是冷启动，这里验证热路径也一致）
        b1_text.run_graph(qs, GRAPHS["v1"], a, stub=True, cache_dir=tmp / "cache_a")
        assert a.read_bytes() == b.read_bytes(), "B1 缓存命中路径与冷启动结果不一致"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- B1：负控的定义性性质 —— v1/v2 只有 version 与 graph 不同
    for r1, r2 in zip(cells[("b1_text", "v1")], cells[("b1_text", "v2")]):
        skip_top = ("version", "branch", "meta")     # 这三项按定义随版本变化
        d1 = {k: v for k, v in r1.items() if k not in skip_top}
        d2 = {k: v for k, v in r2.items() if k not in skip_top}
        assert d1 == d2, f"{r1['qid']}: B1 的 v1/v2 输出不同 —— 语料被版本污染了"
        # meta 里必然不同的是 graph / version / branch（三者都随版本变化），其余必须一致
        skip = {"graph", "version", "branch"}
        assert {k: v for k, v in r1["meta"].items() if k not in skip} == \
               {k: v for k, v in r2["meta"].items() if k not in skip}

    # ---- resume 不许丢行：先跑 5 题，再 resume 跑满 19 题
    # 2026-11-17 全量跑踩到：resume 把旧行读进内存却没写进 tmp，os.replace 一执行
    # 已跑完的题就没了，而且退出码仍是 0。这里的断言就是钉这个行为。
    tmp = Path(tempfile.mkdtemp(prefix="resume_"))
    try:
        for name, fn in (("b1_text", b1_text.run_graph), ("bfs2", b2_bfs.run_graph)):
            out = tmp / f"{name}.jsonl"
            cdir = tmp / f"c_{name}"
            fn(qs[:5], GRAPHS["v1"], out, stub=True, cache_dir=cdir)
            first = _read_rows(out)
            assert len(first) == 5, f"{name}: 首段应 5 行，实际 {len(first)}"
            fn(qs, GRAPHS["v1"], out, stub=True, cache_dir=cdir, resume=True)
            rows = _read_rows(out)
            assert len(rows) == len(qs), \
                f"{name}: resume 后 {len(rows)} 行 != {len(qs)} 行（旧行被 os.replace 丢了）"
            assert len({r["qid"] for r in rows}) == len(qs), f"{name}: resume 后出现重复 qid"
            kept = {r["qid"]: r for r in rows}
            for r in first:
                assert kept[r["qid"]] == r, f"{name}: resume 改写了已完成的 {r['qid']}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 同一 prompt 并发只许真正调用一次（缓存竞态）
    # 2026-11-17 全量跑：B1 的 v1/v2 两个 cell 并发抢同一 prompt，各自未命中缓存、
    # 各调一次 API，服务端给了两个不同答案，负控因此出现 6 条翻转。锁 + 拿锁后重读
    # 缓存是修法；这里用假 _live_answer 放大竞态窗口把它钉住。
    tmp = Path(tempfile.mkdtemp(prefix="race_"))
    calls = []
    guard = threading.Lock()
    real_live = llm._live_answer

    def _fake_live(prompt, model, temperature, seed, effort):
        with guard:
            calls.append(prompt)
            n = len(calls)
        time.sleep(0.3)
        return {"text": f"answer-{n}", "usage": {}, "latency_ms": 1, "attempts": 1,
                "http_status": 200, "has_reasoning_content": False,
                "system_fingerprint": "test", "model": model}

    llm._live_answer = _fake_live
    try:
        outs = []

        def _work():
            outs.append(llm.ask("同一个 prompt", stub=False, cache_dir=tmp))

        threads = [threading.Thread(target=_work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(calls) == 1, f"同一 prompt 并发被调用 {len(calls)} 次（缓存锁失效）"
        assert len(set(outs)) == 1, f"并发返回不一致：{sorted(set(outs))}"
        assert not list(tmp.glob("*.lock")), "锁文件未被清理"
    finally:
        llm._live_answer = real_live
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 表：method × version 的作答数
    print("\n每格统计（stub 模式，答案非空计为作答）")
    print(f"{'method':<9}{'version':<9}{'rows':>5}{'answered':>10}{'evid_max':>10}{'evid_avg':>10}")
    print("-" * 53)
    for (method, ver), rows in sorted(cells.items()):
        ans = sum(1 for r in rows if r["answer"])
        ev = [len(r["evidence"]) for r in rows]
        print(f"{method:<9}{ver:<9}{len(rows):>5}{ans:>10}{max(ev):>10}{sum(ev)/len(ev):>10.1f}")

    print("\n作答数（method × version）")
    print(f"{'method':<10}{'v1':>6}{'v2':>6}{'diff':>7}")
    print("-" * 29)
    for method in ("b1_text", "bfs2"):
        a1 = sum(1 for r in cells[(method, "v1")] if r["answer"])
        a2 = sum(1 for r in cells[(method, "v2")] if r["answer"])
        print(f"{method:<10}{a1:>6}{a2:>6}{a2 - a1:>+7}")

    b1flip = sum(1 for r1, r2 in zip(cells[("b1_text", "v1")], cells[("b1_text", "v2")])
                 if r1["answer"] != r2["answer"])
    b2flip = sum(1 for r1, r2 in zip(cells[("bfs2", "v1")], cells[("bfs2", "v2")])
                 if r1["answer"] != r2["answer"])
    print(f"\n答案翻转数（v1→v2）：b1_text={b1flip}  bfs2={b2flip}"
          f"   [B1 必须为 0：负控；B2 的翻转目前只是 stub 的产物，无科学含义]")
    print(f"stub={llm._stub_answer.__name__} temperature={llm.TEMPERATURE} seed={llm.SEED} "
          f"cache={llm.CACHE_DIR}")
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
