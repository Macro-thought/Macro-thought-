#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T1.4 标签独立校验（G3 闸门）
============================
三件事，都不许复用 labels/solver.py 的代码：

1. **实现隔离**：AST 扫 `labels/*.py` 的 import，确认没有 ops/、baselines/、fetch_subgraph；
   反向也扫 `ops/*.py`，确认没有 import labels。用 ast 而不是 grep——字符串注释、
   `from . import`、`importlib.import_module` 都能绕过 grep。
2. **独立重算**：用另一套图遍历实现（全表扫描 + 不动点，而非邻接表 + 递归）重算全部
   19 题 × 5 分支，与 data/qa_smoke.jsonl 逐行比对。
3. **可人工复核的证据**：抽 3 题打印"答案 + 支撑边"，供 A/C 用眼睛在图里对数。

    python scripts/verify_labels.py
"""

import ast
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BANNED_IN_LABELS = ("ops", "baselines", "fetch_subgraph", "apply_ops")
BANNED_IN_OPS = ("labels", "solver")


# ---------------------------------------------------------------- 1. AST 隔离检查

def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
            if node.level:                      # from . import x
                mods.add("<relative>")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in ("import_module", "__import__"):
                mods.add("<dynamic>")
    return mods


def check_isolation():
    ok = True
    print("== 1. 实现隔离（AST）==")
    label_files = sorted((ROOT / "labels").glob("*.py"))
    for p in label_files:
        mods = imports_of(p)
        bad = mods & set(BANNED_IN_LABELS)
        print(f"  {p.relative_to(ROOT)}: imports {sorted(mods)} "
              f"{'OK' if not bad else 'FAIL ' + str(sorted(bad))}")
        ok &= not bad
    for p in sorted((ROOT / "ops").glob("*.py")):
        mods = imports_of(p)
        bad = mods & set(BANNED_IN_OPS)
        print(f"  {p.relative_to(ROOT)}: imports {sorted(mods)} "
              f"{'OK' if not bad else 'FAIL ' + str(sorted(bad))}")
        ok &= not bad
    return ok


# ---------------------------------------------------------------- 2. 独立重算

class Flat:
    """与 solver 完全不同的实现：全表扫描 + 迭代到不动点，无邻接表、无递归。"""

    def __init__(self, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.ents = {e["id"]: e for e in d["entities"]}
        self.E = d["edges"]

    def subclasses(self, c):
        got = {c}
        changed = True
        while changed:
            changed = False
            for e in self.E:
                if e["r"] == "P279" and e["t"] in got and e["h"] not in got:
                    got.add(e["h"])
                    changed = True
        return got

    def inst(self, c):
        cls = self.subclasses(c)
        return {e["h"] for e in self.E if e["r"] == "P31" and e["t"] in cls}

    def tails(self, h, r):
        return {e["t"] for e in self.E if e["h"] == h and e["r"] == r}

    def lab(self, i):
        return (self.ents.get(i) or {}).get("label_zh") or i

    def ans(self, q):
        op = q["op"]
        if op == "count_class":
            return {"type": "int", "value": len(self.inst(q["class"]))}
        if op == "count_class_country":
            return {"type": "int",
                    "value": len({x for x in self.inst(q["class"])
                                  if (self.ents.get(x) or {}).get("country") == q["country"]})}
        if op == "count_rel":
            return {"type": "int", "value": len(self.tails(q["head"], q["rel"]))}
        if op == "list_rel":
            return {"type": "set", "value": [self.lab(t) for t in sorted(self.tails(q["head"], q["rel"]))]}
        if op == "list_class":
            return {"type": "set", "value": [self.lab(t) for t in sorted(self.inst(q["class"]))]}
        if op == "count_with_rel":
            return {"type": "int",
                    "value": len({x for x in self.inst(q["class"]) if self.tails(x, q["rel"])})}
        if op == "universal_rel":
            s = self.inst(q["class"])
            return {"type": "bool", "value": bool(s) and all(self.tails(x, q["rel"]) for x in s)}
        if op == "hop2_head":
            vals = set()
            for mid in self.tails(q["head"], q["rel1"]):
                vals |= self.tails(mid, q["rel2"])
            return {"type": "int", "value": len(vals)}
        if op == "hop2_distinct":
            vals = set()
            for x in self.inst(q["class"]):
                for mid in self.tails(x, q["rel1"]):
                    vals |= self.tails(mid, q["rel2"])
            return {"type": "int", "value": len(vals)}
        raise ValueError(op)


def check_recompute():
    qa = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA / "qa_smoke.jsonl"
    rows = [json.loads(l) for l in qa.read_text(encoding="utf-8").splitlines() if l.strip()]
    cache, bad = {}, []
    for r in rows:
        for side, graph in (("gold_v1", r["v1_graph"]), ("gold_v2", r["v2_graph"])):
            if graph not in cache:
                cache[graph] = Flat(DATA / graph)
            got = cache[graph].ans(r["query"])
            if got != r[side]:
                bad.append((r["qid"], r["branch"], side, r[side], got))
    print(f"== 2. 独立重算（{qa.name}）== {len(rows)} 行 × 2 版 = {len(rows) * 2} 次求解，"
          f"不一致 {len(bad)} 次")
    for b in bad[:5]:
        print("   !", b)
    return not bad


# ---------------------------------------------------------------- 3. 可人工复核证据

def show_evidence():
    print("== 3. 人工复核（3 例，含支撑边）==")
    cases = [("graph_v1.json", "Q213140", "P113", "日本航空的枢纽"),
             ("graph_v2_restrict.json", "Q213140", "P113", "收窄后日本航空的枢纽"),
             ("graph_v1_mb.json", "Q46970", "P31", "合成基线里的航空公司实例数")]
    for graph, subj, rel, desc in cases:
        g = Flat(DATA / graph)
        if rel == "P31":
            n = len(g.inst(subj))
            print(f"  {desc}（{graph}）：{n} 个实例（闭包）")
            continue
        tails = sorted(g.tails(subj, rel))
        print(f"  {desc}（{graph}）：{len(tails)} 个 → "
              f"{[g.lab(t) for t in tails]}；国家 "
              f"{[(g.ents.get(t) or {}).get('country') for t in tails]}")


def main():
    ok1 = check_isolation()
    ok2 = check_recompute()
    show_evidence()
    print("\n结论：", "通过" if ok1 and ok2 else "有未通过项")
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
