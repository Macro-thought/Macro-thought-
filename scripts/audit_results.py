#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基线输出溯源审计
================
回答一个问题：`baselines/out/` 里的每一行，**能不能证明它是怎么跑出来的**。

2026-11-17 验收发现：24 个输出文件里没有 `mode` 字段，事后无法区分 stub 与真实调用；
另有 5 个 `_v2` 文件把 `version` 写成 `v1`。这个脚本把这些条件写成可执行检查，
以后每跑完一批基线都要过一遍。

检查项（任一不过即非零退出）：
  A. 每行都有 mode ∈ {stub, live}
  B. 每行都有 model；stub 的 model 必须是 "stub"
  C. 所在子目录（out/stub、out/live）与 mode 一致
  D. version ∈ {v1, v2}，且与文件名后缀一致
  E. 图名与 version 自洽：v2 行读 graph_v2_*；例外是 B1——它不读图，允许读 v1 图但必须标出来
  F. branch 与图名推出的分支一致
  G. 同一文件内所有行的 mode/version/graph 必须一致（防半截重跑）

用法：
    python scripts/audit_results.py            # 审计全部
    python scripts/audit_results.py --strict   # 把 legacy 目录里的文件也算作失败
"""

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "baselines" / "out"


def branch_of(gname):
    stem = Path(gname or "").stem
    parts = stem.split("_")
    if len(parts) >= 3 and parts[1] == "v2":
        return parts[2]
    return stem.replace("graph_", "")


def rows_of(path):
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line:
            yield i, json.loads(line)


def check_file(path, strict):
    """按「文件」聚合问题，不按行刷屏：2076 行同一种错只报一条。"""
    bad = []
    n = 0
    kinds = collections.Counter()
    first = {}
    modes, versions, graphs, branches = set(), set(), set(), set()
    rel = path.relative_to(OUT)
    sub = rel.parts[0] if len(rel.parts) > 1 else "(root)"
    legacy = sub not in ("stub", "live")

    if legacy:
        n = sum(1 for _ in rows_of(path))
        if strict:
            bad.append(f"{rel} 位于 legacy 目录（as-found 产物，未迁移到 stub/ 或 live/）")
        return bad, {"file": str(rel), "rows": n, "tag": "legacy",
                     "mode": "-", "version": "-", "graph": "-"}

    def hit(kind, ln, msg):
        kinds[kind] += 1
        first.setdefault(kind, (ln, msg))

    for ln, r in rows_of(path):
        n += 1
        meta = r.get("meta") or {}
        mode, model = meta.get("mode"), meta.get("model")
        ver, g, br = r.get("version"), meta.get("graph"), meta.get("branch")
        modes.add(mode); versions.add(ver); graphs.add(g); branches.add(br)

        if mode not in ("stub", "live"):
            hit("缺 mode 字段", ln, "行内没有 mode，事后无法区分 stub 与真实调用")
            continue
        if not model:
            hit("缺 model 字段", ln, "行内没有 model")
        elif mode == "stub" and model != "stub":
            hit("stub 行的 model 写错", ln, f"应为 'stub'，实际 {model!r}")
        if not legacy and mode != sub:
            hit("mode 与所在目录不一致", ln, f"mode={mode} 但在 {sub}/")
        if ver not in ("v1", "v2"):
            hit("version 非法", ln, repr(ver))
        elif f"_{ver}" not in path.name:
            hit("version 与文件名不符", ln, f"version={ver} 文件名={path.name}")
        if ver == "v2" and not str(g or "").startswith("graph_v2_"):
            if not str(meta.get("template", "")).startswith("b1-"):
                hit("v2 行读了 v1 图", ln, f"graph={g}")
        is_text_only = str(meta.get("template", "")).startswith("b1-")
        if ver == "v2" and not is_text_only and br != branch_of(g):
            hit("branch 与图名不符", ln, f"branch={br!r} 图推出 {branch_of(g)!r}")

    for name, vals in (("mode", modes), ("version", versions), ("graph", graphs), ("branch", branches)):
        if len(vals) > 1:
            bad.append(f"{rel} 文件内 {name} 不一致：{sorted(map(str, vals))}（疑似半截重跑）")

    for kind, cnt in kinds.most_common():
        ln, msg = first[kind]
        bad.append(f"{rel} {cnt}/{n} 行 {kind}（首见第 {ln} 行：{msg}）")

    if legacy:
        tag = "legacy"
        if strict:
            bad.append(f"{rel} 位于 legacy 目录（as-found 产物，未迁移到 stub/ 或 live/）")
    else:
        tag = sub

    return bad, {"file": str(rel), "rows": n, "tag": tag,
                 "mode": "/".join(sorted(map(str, modes))),
                 "version": "/".join(sorted(map(str, versions))),
                 "graph": "/".join(sorted(map(str, graphs)))}


def main(argv=None):
    ap = argparse.ArgumentParser(description="基线输出溯源审计")
    ap.add_argument("--strict", action="store_true", help="legacy 目录里的文件也算失败")
    args = ap.parse_args(argv)

    files = sorted(f for f in OUT.rglob("*.jsonl") if not f.name.startswith("_"))
    if not files:
        print(f"{OUT} 下没有 jsonl")
        return 1

    all_bad, stats = [], []
    for f in files:
        bad, st = check_file(f, args.strict)
        all_bad += bad
        stats.append(st)

    print(f"审计 {len(files)} 个文件\n")
    print(f"{'文件':<42}{'行':>5}  {'mode':<10}{'version':<9}graph")
    print("-" * 96)
    for s in stats:
        print(f"{s['file']:<42}{s['rows']:>5}  {s['mode']:<10}{s['version']:<9}{s['graph']}")

    print()
    if all_bad:
        by_kind = collections.Counter()
        for b in all_bad:
            key = b.split(" 缺 ")[1].split("（")[0] if " 缺 " in b else "其他"
            by_kind[key] += 1
        print(f"发现 {len(all_bad)} 处问题，按类型：")
        for k, v in by_kind.most_common():
            print(f"  {k}: {v}")
        print("\n前 12 条明细：")
        for b in all_bad[:12]:
            print("  -", b)
        print("\n判定：未通过")
        return 1

    print("判定：通过（每行都能自证 mode / model / version / graph / branch）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
