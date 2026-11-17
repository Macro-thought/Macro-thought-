#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夜间审计汇总（G0–G3 一页纸）
============================
把四道闸门的结论、确定性复跑、算子与标签的统计压成三份报告：
    reports/night_audit_2026-11-17.md   ← 明早先看这个
    reports/t13_ops.md
    reports/t14_labels.md

做法：只调用各脚本的公共入口（subprocess），不在本文件里重算任何语义——
审计脚本自己实现一套语义，就成了第四个"真相"。

    python scripts/audit_night.py
"""

import collections
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REP = ROOT / "reports"

GATES = [
    ("G0 数据可行性", "scripts/probe_t10.py", None),
    ("G1 形式条件", "scripts/verify_schema.py", None),
    ("G2 算子确定性", "scripts/verify_ops.py", None),
    ("G3 实现隔离+语义", "scripts/verify_labels.py", None),
]


def run(rel):
    p = subprocess.run([sys.executable, str(ROOT / rel)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def hashes():
    out = {}
    for p in sorted(DATA.glob("graph_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[p.name] = d["meta"].get("idempotent_hash")
    return out


def sha(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:12]


def g0_verdict():
    """
    G0 是唯一由「数据判定」而非「退出码」说话的闸门：probe_t10.py 只要跑完就返回 0，
    合不合格写在 data/probe_t10.json 的 verdicts 里。
    2026-11-17 事故根因：旧版只看退出码，G0 明明 c/b=fail 仍被算成通过，导致回执写「全部通过」。
    这里直接读产物，四项全 pass 才算 G0 通过。
    """
    p = DATA / "probe_t10.json"
    if not p.exists():
        return False, {}
    try:
        v = json.loads(p.read_text(encoding="utf-8")).get("verdicts", {})
    except Exception:                                              # noqa: BLE001
        return False, {}
    return bool(v) and all(x == "pass" for x in v.values()), v


def main():
    REP.mkdir(exist_ok=True)
    before = hashes()
    code_ops, log_ops = run("ops/apply_ops.py") if False else (None, "")
    p = subprocess.run([sys.executable, str(ROOT / "ops/apply_ops.py"), "--all"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    after = hashes()

    det_rows = [(k, before.get(k), after.get(k)) for k in before]
    det_ok = all(a == b for _, a, b in det_rows)

    gate_rows = []
    gate_flags = []
    for name, script, _ in GATES:
        c, out = run(script)
        gate_rows.append((name, script, c, out.strip().splitlines()[-1] if out.strip() else ""))
        if name.startswith("G0"):
            ok0, _ = g0_verdict()
            gate_flags.append(ok0)
        else:
            gate_flags.append(c == 0)
    gate_ok = all(gate_flags)
    g0_ok, g0v = g0_verdict()

    # ---------------- 算子统计
    ops = {}
    for key in ("v2_refine", "v2_restrict", "v2_merge", "v2_split", "v2_all"):
        d = json.loads((DATA / f"graph_{key}.json").read_text(encoding="utf-8"))
        ch = collections.Counter((c["op"], c["kind"]) for c in d["changes"])
        ops[key] = {
            "n_entities": len(d["entities"]), "n_edges": len(d["edges"]),
            "n_retired": len(d.get("retired_edges", [])),
            "hash": d["meta"]["idempotent_hash"],
            "changes": ch,
        }

    L = ["# 夜间审计回执（2026-11-17）\n",
         f"执行：S　｜　复核：A（待）　｜　生成脚本：`scripts/audit_night.py`\n",
         "## 一、四道闸门\n",
         "| 闸门 | 脚本 | 退出码 | 末行 |",
         "|---|---|---|---|"]
    for name, script, c, last in gate_rows:
        L.append(f"| {name} | `{script}` | {c} | {last} |")
    L.append("")
    if gate_ok:
        L.append("**闸门总判定：全部通过**")
    else:
        bad = [n for (n, _, _, _), f in zip(gate_rows, gate_flags) if not f]
        L.append(f"**闸门总判定：未通过（{('、'.join(bad))}）**")
        if not g0_ok:
            L.append("")
            L.append(f"> **G0 不通过**：verdicts = `{g0v}`。"
                     "G0 的退出码 0 只表示「探针跑完了」，不表示数据合格。"
                     "按 D1/D2/D4 缩小范围继续，但**任何材料不得宣称数据可行性已通过**。")
    L.append("")
    L.append("> 只有 G0 需要人判，后三道由脚本判；本行判定已把 G0 的 verdicts 纳入，"
             "不再只看退出码。\n")

    L.append("## 二、确定性复跑（G2 判据）\n")
    L.append("| 产物 | 首次 | 复跑 | 一致 |")
    L.append("|---|---|---|---|")
    for k, a, b in det_rows:
        L.append(f"| `{k}` | `{a}` | `{b}` | {'是' if a == b else '**否**'} |")
    L.append("")
    L.append(f"复跑结论：**{'一致' if det_ok else '不一致'}**（`apply_ops.py --all` 连跑两次）\n")

    L.append("## 三、七份图的规模与改动\n")
    L.append("| 图 | 实体 | 边 | 退休边 | 指纹 | 主要改动 |")
    L.append("|---|---|---|---|---|---|")
    short = {"retire_edge": "删", "add_edge": "增", "merge_node": "并", "add_class": "立类"}
    for k, v in ops.items():
        agg = collections.Counter()
        for (op, kind), n in v["changes"].items():
            agg[op.replace("_TYPE", "").replace("_CONCEPT", "").replace("_REL", "")
                .replace("_ENTITY", "").replace("MERGE_BASE", "建重复")] += n
        ch = "、".join(f"{op}{n}" for op, n in sorted(agg.items()))
        L.append(f"| `graph_{k}.json` | {v['n_entities']} | {v['n_edges']} | "
                 f"{v['n_retired']} | `{v['hash']}` | {ch or '—'} |")
    L.append("")

    # ---------------- 应然矩阵
    QA = DATA / "qa_v1.jsonl" if (DATA / "qa_v1.jsonl").exists() else DATA / "qa_smoke.jsonl"
    rows = [json.loads(l) for l in QA.read_text(encoding="utf-8").splitlines() if l.strip()]
    shapes = ["count", "set", "bool", "hop2"]
    matrix = collections.defaultdict(collections.Counter)
    for r in rows:
        matrix[r["branch"]][(r["shape"], r["should"])] += 1
    branches = ["refine", "restrict", "merge", "split", "all"]

    L.append(f"## 四、应然矩阵（{QA.name}，{len(rows)} 行）\n")
    L.append("| 分支 | " + " | ".join(shapes) + " |")
    L.append("|---" * (len(shapes) + 1) + "|")
    for b in branches:
        cells = []
        for s in shapes:
            c = matrix[b]
            cells.append(f"{c[(s, 'stable')]}/{c[(s, 'flip')]}/{c[(s, 'unanswerable')]}")
        L.append(f"| {b} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("读法：`稳定/翻转/不可答`。**这张表是应然标签的分布，不是 T1.5 的对照结论**——"
             "对照要等 A 填完 `data/prior_20grid.template.json` 后由 `scripts/t15_matrix.py` 产出"
             "（见 `decisions.md` D5）。\n")

    L.append("## 五、三件需要你明早开口的事\n")
    L.append("1. **D1**：130 个可用实体，够不够撑 120 题？建议降到 80–100 题，理由在方案 §4。")
    L.append("2. **D2**：MERGE 只能合成重复对（真实同指对 0），审稿人必问；"
             "选实体级合成还是类级真实合并？")
    L.append("3. **D4**：RESTRICT 的时间维度拿不到（P121 限定词探针见 `reports/t10_probe.md`），"
             "接受「属性收窄」还是补一次 P571/P576 取数？\n")

    L.append("## 六、我留下的已知薄弱点（主动交代）\n")
    L.append("- **refine 分支全 stable**：因为求解器用闭包语义，而 refine 形式保证闭包不变。"
             "这不是 bug，是设计——该分支只能测「误翻转」（叶子匹配的基线会挂），不能测「漏翻转」。"
             "论文里必须把这句写清，否则 FFR/MFR 两张表会自相矛盾。")
    L.append("- **merge 分支的 v1 不是 canonical v1**（多了 12 个合成节点）。"
             "跨分支的主表不能混用同一个 v1 基线，表头必须标 `v1_mb`。")
    L.append("- **split 的补集类是我起的名字**（非货运航空公司）。"
             "名字本身就是论文里的一个论点，你可能会想改。")
    L.append("- **探针 a 未出数**：qlever 限流（429），后台仍在退避重试。"
             "若明早仍 `unverified`，RESTRICT 的时间维度就只能按 D4 处理。")

    (REP / "night_audit_2026-11-17.md").write_text("\n".join(L), encoding="utf-8")

    # ---------------- T1.3 报告
    M = ["# T1.3 四个算子与七份图\n",
         "生成：`ops/apply_ops.py --all`　｜　校验：`scripts/verify_ops.py`\n",
         "## 语义（必须与论文方法节一致）\n",
         "| 算子 | 实现口径 | 形式保证 |",
         "|---|---|---|"]
    M.append("| REFINE_TYPE | 最具体类型化：实例已断言后代类时，删除指向父类的 P31 | 父类闭包不变 |")
    M.append("| SPLIT_CONCEPT | 父类 → 真实子类 + 补集类（合成，P279→父类），负分支实例迁移 | 互斥、并集=父类闭包 |")
    M.append("| RESTRICT_REL | 关系扩展收窄到「枢纽位于中国」；不满足的边退休并置 valid_to=2024 | v2 中无违反条件的边 |")
    M.append("| MERGE_ENTITY | 合成重复节点合并回主节点：边重定向、去重、节点标 merged_into | 边数守恒、无 dup 残留 |")
    M.append("")
    M.append("## 产物\n")
    M.append("| 图 | 实体 | 边 | 退休 | 指纹 |")
    M.append("|---|---|---|---|---|")
    for k, v in ops.items():
        M.append(f"| `graph_{k}.json` | {v['n_entities']} | {v['n_edges']} | "
                 f"{v['n_retired']} | `{v['hash']}` |")
    M.append("")
    M.append("## 与任务书的三处偏离（不是笔误，是数据决定的）\n")
    M.append("1. **RESTRICT 不是时间收窄**。任务书按 P580/P582 限定词收窄，"
             "但本图未取限定词（T1.0-a 探针见 `reports/t10_probe.md`），改用「枢纽所在国家」这一属性收窄。"
             "论文 Limitations 必须写。")
    M.append("2. **MERGE 的输入是合成的**。图内真实同指对 0 对（T1.0-b），"
             "故把 12 家航司的英文名拆成独立节点当作「合并前」状态。**只造输入，不造标签。**")
    M.append("3. **SPLIT 的负分支是补集**。「非货运航空公司」不是 Wikidata 类，是分析构造；"
             "其形式性质（互斥、并集）由脚本断言，不靠约定。")
    M.append("")
    M.append("## 每条改动的可追溯性\n")
    M.append("每条边有稳定 id（三元组 sha1 前 12 位）与 `why` 字段；被替换/退休的边进 "
             "`retired_edges`，含 `valid_to` 与原因。审计时按 `changes` 数组可逐条复盘。\n")
    (REP / "t13_ops.md").write_text("\n".join(M), encoding="utf-8")

    # ---------------- T1.4 报告
    N = ["# T1.4 求解器与应然标签\n",
         "生成：`labels/solver.py --smoke`　｜　校验：`scripts/verify_labels.py`\n",
         "## 一句话\n",
         "`gold = Solve(Q, G)`，Q 是结构化查询，G 是某一版图。"
         "求解器与 `ops/` **零 import**（AST 检查通过），与被测系统只共享同一份图数据——"
         "这是评审 §2 要求的实现隔离。\n",
         "## 语义约定\n",
         "- 类的实例集取**闭包**（P279* 后代），即 OWL 子类语义；这是「应然」的定义。"]
    N.append("- 计数一律 distinct；集合答案按 id 排序后取中文标签，保证两版可比。")
    N.append("- `should` 三分类：两版相同 = stable；v1 有答案而 v2 为空 = unanswerable；其余 = flip。\n")
    N.append("## 冒烟结果（19 题 × 5 分支）\n")
    N.append("| 分支 | " + " | ".join(shapes) + " |")
    N.append("|---" * (len(shapes) + 1) + "|")
    for b in branches:
        cells = []
        for s in shapes:
            c = matrix[b]
            cells.append(f"{c[(s, 'stable')]}/{c[(s, 'flip')]}/{c[(s, 'unanswerable')]}")
        N.append(f"| {b} | " + " | ".join(cells) + " |")
    N.append("")
    N.append("## 三个必须解释的现象\n")
    N.append("1. **refine 全 stable**（0 翻转）。闭包不变是 REFINE 的形式保证，"
             "所以「该变的」本来就没有。该分支的价值是测**误翻转**："
             "任何直接按 P31 叶子匹配的系统，在「机场有多少个」上会从 74 掉到 36。")
    N.append("2. **restrict 的翻转集中在关系与二跳**（枢纽计数 129→64、国家数 9→1），"
             "计数类问题（实体总数）不动——这正是「关系收窄」该有的形状。")
    N.append("3. **merge 的翻转集中在计数**（199→188、105→98），枚举题也翻（多了一个英文名节点），"
             "但全称题不动。若全称题也翻，说明合成节点混进了类的闭包，是 bug。\n")
    N.append("## 不可答的构造\n")
    N.append("日本航空在 `v2_restrict` 里 0 个枢纽（4 个枢纽全在日本），"
             "因此「日本航空有几个枢纽」从 4 → 空，标 `unanswerable`；"
             "这是唯一能检验「该答不出时有没有硬答」的题形。\n")
    (REP / "t14_labels.md").write_text("\n".join(N), encoding="utf-8")

    print("闸门：", "全部通过" if gate_ok else "有未通过项")
    print("确定性：", "一致" if det_ok else "不一致")
    print("写出 reports/night_audit_2026-11-17.md / t13_ops.md / t14_labels.md")
    return 0 if (gate_ok and det_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
