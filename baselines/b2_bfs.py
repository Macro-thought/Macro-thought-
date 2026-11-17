#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B2 两跳 BFS 图检索（**有损**检索）
==================================
从问题里的实体出发，沿边做 2 跳 BFS，取一个小子图 → 读成人话 → LLM 作答。

**这个基线必须是有损的，这不是妥协，是实验设计。** 四条硬约束写死在常量里，
不给命令行开关（`MAX_EDGES` / `HOPS` / `FORBIDDEN_RELS` 都没有 --flag）：
  1. 子图边数上限 **20**（`MAX_EDGES`）；
  2. 固定 **2 跳**（`HOPS`），不按问题难度自适应；
  3. **不给 LLM 任何显式类型/关系白名单**：prompt 里只有具体事实和问句，
     不出现"可用关系：P113/P17…"这类提示。一旦给了白名单，B2 就偷偷拿到了 schema，
     而本研究要测的正是"schema 变了、系统不知道"；
  4. **不读 P279 做推理**：P279 边既不参与扩展也不进子图。gold 侧的类实例集是 P279
     闭包，B2 拿不到闭包 → 计数类问题会系统性地少算。这正是"有损"要暴露的东西。

补充两条实现取舍（都朝"更笨"的方向选）：
  - **无向扩展**：问题既可能"从类找实例"（入边），也可能"从实体找属性"（出边），
    基线不知道算子类型，两个方向都扩。
  - **下一层只从已入选边的端点出发**：被截断的边不会把预算浪费在永远不会出现的邻域上，
    子图保持连通，evidence 也更像一段能读的邻域。

**截断规则（确定性，论文里要原样写）**
  每一跳：收集候选边 → 按 id 去重 → 按 (h, r, t) 字典序排序 → 依次收入直到总数达 20。
  排序键与 graph_access 建索引用的键一致，所以"选哪 20 条"完全由图内容决定，
  与遍历先后、hash 顺序无关。

用法：
    python baselines/b2_bfs.py --graph data/graph_v1.json --out baselines/out/bfs2_v1.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import graph_access as ga
import llm

METHOD = "bfs2"
TEMPLATE_ID = "b2-bfs2-v1"

MAX_EDGES = 20          # 硬约束，不要加命令行开关
HOPS = 2                # 硬约束
FORBIDDEN_RELS = {"P279"}   # 硬约束：不用层级边做推理

PROMPT_TEMPLATE = """你是严谨的航空知识图谱问答助手。下面是从知识图谱中按两跳邻域取出的一小部分事实，可能不完整。你只能依据这些事实作答。

问句：{question}

事实（两跳邻域，已按固定顺序截断）：
{evidence}

答案形式：{form}
输出要求：只输出答案本身；事实不足以确定答案时，只输出"不知道"。
"""


def seeds_of(q):
    """问题里的起点实体。

    取算子的**主语**字段（head / class）。刻意不把 country 这类过滤值也当起点：
    20 条边的预算很紧，从"中华人民共和国"扩一圈会把与问题无关的国家/首都邻域全吃进来，
    那样测到的就不是"检索有损"，而是"起点选错"。
    """
    qd = q.get("query", {})
    for k in ("head", "class"):
        v = qd.get(k)
        if isinstance(v, str) and v.startswith("Q"):
            return [v]
    vals = sorted({v for k, v in qd.items()
                   if isinstance(v, str) and v.startswith("Q") and not k.startswith("rel")})
    return vals


def bfs_subgraph(g, seeds, hops=HOPS, cap=MAX_EDGES):
    """返回子图边列表，长度 ≤ cap；有序（BFS 层序 → 层内按 (h,r,t)）。"""
    picked, seen, frontier = [], set(), sorted({s for s in seeds if s})
    for _ in range(hops):
        cand = {}
        for n in frontier:
            for (r, other, eid, d) in g.incident(n):
                if r in FORBIDDEN_RELS or eid in seen or eid in cand:
                    continue
                if d == "out":
                    cand[eid] = {"h": n, "r": r, "t": other, "id": eid}
                else:
                    cand[eid] = {"h": other, "r": r, "t": n, "id": eid}
        if not cand:
            break
        ordered = sorted(cand.values(), key=lambda e: (e["h"], e["r"], e["t"], e["id"]))

        added = []
        for e in ordered:
            if len(picked) >= cap:
                break            # 预算用完就停在半路，这就是"截断"
            picked.append(e)
            seen.add(e["id"])
            added.append(e)
        if not added:
            break
        # 下一层只从"已入选"边的端点走，保证子图连通、预算不浪费
        nxt = set()
        for e in added:
            nxt.add(e["h"])
            nxt.add(e["t"])
        frontier = sorted(nxt)
    return picked


def _evidence_block(g, edges):
    return "\n".join(
        f"{i}. {g.label(e['h'])} ｜ {ga.r_label(e['r'])} ｜ {g.label(e['t'])} [{e['id']}]"
        for i, e in enumerate(edges, 1))


def branch_of(gname: str) -> str:
    """graph_v2_split.json -> split；graph_v1.json -> v1。"""
    stem = Path(gname).stem
    parts = stem.split("_")
    if len(parts) >= 3 and parts[1] == "v2":
        return parts[2]
    return stem.replace("graph_", "")


def run_graph(questions, graph_path, out_path, *, stub=True, cache_dir=None, version=None, branch=None, resume=False):
    g = ga.Graph.load(graph_path)
    gname = Path(graph_path).name
    version = version or g.version        # 未显式覆盖时以图自身的 meta.version 为准
    branch = branch or branch_of(gname)
    cdir = Path(cache_dir) if cache_dir else llm.CACHE_DIR

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    rows, done = [], set()
    if resume and out.exists():
        for line in out.read_text("utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows.append(r)
                done.add(r["qid"])
        print(f"    resume: 已有 {len(done)} 行，跳过这些题")
    fh = tmp.open("w", encoding="utf-8", newline="\n")
    # resume 捞回的旧行必须先写进 tmp，否则末尾 os.replace 会用只含新行的
    # tmp 覆盖旧文件，断点续跑反而把已经跑完的题丢掉（2026-11-17 全量跑时踩到）。
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    fh.flush()

    for q in questions:
        if q["qid"] in done:
            continue
        question = q.get("nl") or json.dumps(q.get("query", {}), ensure_ascii=False)
        edges = bfs_subgraph(g, seeds_of(q))
        prompt = PROMPT_TEMPLATE.format(
            question=question,
            evidence=_evidence_block(g, edges) if edges else "（无可用事实）",
            form=llm.answer_form(q["shape"]))
        raw, err = llm.safe_ask(prompt, stub=stub, cache_dir=cdir)
        row = {
            "qid": q["qid"],
            "method": METHOD,
            "version": version,        # 与 --version 一致；默认取图的 meta.version
            "branch": branch,          # score.py 只认顶层 branch
            "answer": llm.parse_answer(raw, q["shape"]),
            "evidence": [e["id"] for e in edges],
            "raw": raw,
            "meta": {
                "temperature": llm.TEMPERATURE,
                "version": version,              # 本行声称对应的版本
                "branch": branch,
                "mode": llm.mode_name(stub),     # stub / live
                "model": llm.model_name(),
                "seed": llm.SEED,
                "graph": gname,
                "template": TEMPLATE_ID,
            },
        }
        if err:
            row["meta"]["error"] = err
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        rows.append(row)

    fh.close()
    os.replace(tmp, out)                      # 全部成功才替换，半截文件不会被当成结果
    order = {q["qid"]: i for i, q in enumerate(questions)}
    rows.sort(key=lambda r: order.get(r["qid"], 10 ** 9))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="B2 两跳 BFS 有损图检索")
    ap.add_argument("--questions", default="data/questions_smoke.json")
    ap.add_argument("--graph", default="data/graph_v1.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--live", action="store_true", help="真实调用（默认 stub，不联网）")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--version", default=None)
    ap.add_argument("--branch", default=None, help="变更分支；不给则由图名推断")
    ap.add_argument("--resume", action="store_true", help="跳过输出文件里已有的 qid")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 题（pilot 用）")
    ap.add_argument("--qids", default=None, help="只跑指定 qid，逗号分隔")
    args = ap.parse_args(argv)

    qs = json.loads(Path(args.questions).read_text("utf-8"))["questions"]
    if args.qids:
        want = {x.strip() for x in args.qids.split(",") if x.strip()}
        qs = [q for q in qs if q["qid"] in want]
    if args.limit:
        qs = qs[:args.limit]
    version = args.version or ga.read_version(args.graph)
    out = args.out or f"baselines/out/{llm.mode_name(not args.live)}/{METHOD}_{args.branch or version}_{version}.jsonl"
    rows = run_graph(qs, args.graph, out, stub=not args.live, cache_dir=args.cache_dir,
                     version=version, branch=args.branch, resume=args.resume)
    n_ans = sum(1 for r in rows if r["answer"])
    print(f"[{METHOD}] mode={'live' if args.live else 'stub'} graph={Path(args.graph).name} "
          f"rows={len(rows)} answered={n_ans} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
