# 夜间审计回执（2026-11-17）

执行：S　｜　复核：A（待）　｜　生成脚本：`scripts/audit_night.py`

## 一、四道闸门

| 闸门 | 脚本 | 退出码 | 末行 |
|---|---|---|---|
| G0 数据可行性 | `scripts/probe_t10.py` | 0 | 判定： {'c': 'fail', 'b': 'fail', 'd': 'partial', 'a': 'unverified'} |
| G1 形式条件 | `scripts/verify_schema.py` | 0 | 结论： 通过 |
| G2 算子确定性 | `scripts/verify_ops.py` | 0 | 结论： 全部通过 |
| G3 实现隔离+语义 | `scripts/verify_labels.py` | 0 | 结论： 通过 |

**闸门总判定：未通过（G0 数据可行性）**

> **G0 不通过**：verdicts = `{'c': 'fail', 'b': 'fail', 'd': 'partial', 'a': 'unverified'}`。G0 的退出码 0 只表示「探针跑完了」，不表示数据合格。按 D1/D2/D4 缩小范围继续，但**任何材料不得宣称数据可行性已通过**。

> 只有 G0 需要人判，后三道由脚本判；本行判定已把 G0 的 verdicts 纳入，不再只看退出码。

## 二、确定性复跑（G2 判据）

| 产物 | 首次 | 复跑 | 一致 |
|---|---|---|---|
| `graph_v1.json` | `d5935c6c56f97176` | `d5935c6c56f97176` | 是 |
| `graph_v1_mb.json` | `68e3df22473ccb31` | `68e3df22473ccb31` | 是 |
| `graph_v2_all.json` | `430322e9f0a264c8` | `430322e9f0a264c8` | 是 |
| `graph_v2_merge.json` | `0ca659e95cc973dd` | `0ca659e95cc973dd` | 是 |
| `graph_v2_refine.json` | `4f3e0d28e2a70f72` | `4f3e0d28e2a70f72` | 是 |
| `graph_v2_restrict.json` | `87fb131119998713` | `87fb131119998713` | 是 |
| `graph_v2_split.json` | `b6fd1e440ef43acc` | `b6fd1e440ef43acc` | 是 |

复跑结论：**一致**（`apply_ops.py --all` 连跑两次）

## 三、七份图的规模与改动

| 图 | 实体 | 边 | 退休边 | 指纹 | 主要改动 |
|---|---|---|---|---|---|
| `graph_v2_refine.json` | 590 | 1819 | 38 | `4f3e0d28e2a70f72` | REFINE38 |
| `graph_v2_restrict.json` | 590 | 1768 | 89 | `87fb131119998713` | RESTRICT89 |
| `graph_v2_merge.json` | 590 | 1857 | 73 | `0ca659e95cc973dd` | MERGE85、建重复73 |
| `graph_v2_split.json` | 591 | 1861 | 174 | `b6fd1e440ef43acc` | SPLIT353 |
| `graph_v2_all.json` | 591 | 1734 | 374 | `430322e9f0a264c8` | MERGE85、REFINE38、RESTRICT89、SPLIT353、建重复73 |

## 四、应然矩阵（qa_v1.jsonl，500 行）

| 分支 | count | set | bool | hop2 |
|---|---|---|---|---|
| refine | 32/0/0 | 24/0/0 | 16/0/0 | 28/0/0 |
| restrict | 29/1/2 | 19/0/5 | 16/0/0 | 13/2/13 |
| merge | 25/7/0 | 23/1/0 | 16/0/0 | 28/0/0 |
| split | 30/2/0 | 24/0/0 | 16/0/0 | 28/0/0 |
| all | 21/9/2 | 18/1/5 | 16/0/0 | 13/2/13 |

读法：`稳定/翻转/不可答`。**这张表是应然标签的分布，不是 T1.5 的对照结论**——对照要等 A 填完 `data/prior_20grid.template.json` 后由 `scripts/t15_matrix.py` 产出（见 `decisions.md` D5）。

## 五、三件需要你明早开口的事

1. **D1**：130 个可用实体，够不够撑 120 题？建议降到 80–100 题，理由在方案 §4。
2. **D2**：MERGE 只能合成重复对（真实同指对 0），审稿人必问；选实体级合成还是类级真实合并？
3. **D4**：RESTRICT 的时间维度拿不到（P121 限定词探针见 `reports/t10_probe.md`），接受「属性收窄」还是补一次 P571/P576 取数？

## 六、我留下的已知薄弱点（主动交代）

- **refine 分支全 stable**：因为求解器用闭包语义，而 refine 形式保证闭包不变。这不是 bug，是设计——该分支只能测「误翻转」（叶子匹配的基线会挂），不能测「漏翻转」。论文里必须把这句写清，否则 FFR/MFR 两张表会自相矛盾。
- **merge 分支的 v1 不是 canonical v1**（多了 12 个合成节点）。跨分支的主表不能混用同一个 v1 基线，表头必须标 `v1_mb`。
- **split 的补集类是我起的名字**（非货运航空公司）。名字本身就是论文里的一个论点，你可能会想改。
- **探针 a 未出数**：qlever 限流（429），后台仍在退避重试。若明早仍 `unverified`，RESTRICT 的时间维度就只能按 D4 处理。