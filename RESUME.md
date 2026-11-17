# RESUME.md — 长程状态与恢复入口

> 给「下一次接手的人或 agent」看的。**新会话先读这一页，再读 `decisions.md`，不要重新问一遍已经定过的事。**
> 最后更新：2026-11-17 18:35（S，噪声底噪之后）

---

## 0. 三十秒版本

- 项目：Wikidata 航空子图上做 **schema 级结构变更**（4 算子），看多跳问答的旧答案还成不成立。
- 已完成：**T1.0 探针 → T1.1 取图 → T1.2 类型 → T1.3 四算子 → T1.4 求解器 → T1.5 脚手架 → T2.1 模板 → T2.2 100 题 → 指标 → 文献/会议核实 → pilot → 全量基线（2000 行）→ 噪声底噪**。
- **主表的关键事实**：500 个 v1↔v2 配对里 **251 个证据没变**（prompt 相同 → 缓存 → 翻转必然 0），
  **249 个证据变了**（翻转 0.277）；同一 prompt 重采样的**噪声底噪 0.180**。效应比噪声只高 +0.097（近似 p=0.042，偏乐观）。
- 离线全链 3.3 秒：`python scripts/audit_night.py`（G0 不通过时退出码 1，属预期）。
- **卡在人的判断上**：① 主结论要不要改成「证据变化子集 vs 噪声」的写法；② 要不要用 3 次采样投票压噪声（约 +¥3）；③ D1–D5；④ B3 做还是 descope。
- 一句话结论：**管线、标签、基线、底噪都齐了；现在缺的不是数据，是「这个效应撑不撑得住一篇论文」的判断。**

---

## 1. 现在有什么（可直接复跑）

```bash
cd <仓库根目录>
python scripts/probe_t10.py                 # T1.0 四探针（离线；--with-a 才联网）
python scripts/build_schema.py              # T1.2 类型树 + 算子计划
python ops/apply_ops.py --all               # T1.3 五份 v2 图
python scripts/gen_questions.py             # T2.2 100 题
python labels/solver.py --questions data/questions_v1.json --out data/qa_v1.jsonl
python scripts/t15_matrix.py                # 应然矩阵（先验未确认时只出实测）
python scripts/audit_night.py               # 四道闸门 + 三份报告（G0 不过 → 退出码 1）
python scripts/audit_results.py             # 基线输出溯源（86 个文件：legacy 24 / stub 20 / live 21 / 归档 21）
python scripts/run_live.py --full --workers 6   # 重跑全量（命中 .cache_live，9 秒、零花费）
python metrics/tests_smoke.py               # 指标 53 个用例
python baselines/tests_smoke.py             # 基线冒烟（含 resume 不丢行、并发缓存锁两组回归）
python scripts/noise_floor.py --analyze-only # 噪声底噪 + 分层（不重跑，读 existing 输出）
```

关键产物：

| 文件 | 是什么 | 能不能信 |
|---|---|---|
| `data/graph_v1.json` | canonical 图（只读，指纹 `d5935c6c56f97176`） | 可复现 |
| `data/graph_v1_mb.json` | merge 分支的基线（v1 + 12 个合成重复节点） | **合成输入，不是 canonical v1** |
| `data/graph_v2_*.json` | 5 份变更后图，各带 `retired_edges` + `changes` | 可逐条审计 |
| `data/questions_v1.json` | 100 题（32 count / 24 set / 16 bool / 28 hop2） | 题面已过 4 条自检 |
| `data/qa_v1.jsonl` | 100 题 × 5 分支 = 500 行 gold + should | 500 行 × 2 个独立实现零分歧 |
| `data/prior_20grid.template.json` | **待 A 填的先验**（20 格 = 5 分支 × 4 答形） | 空 |
| `data/prior_draft_by_S.json` | S 的草稿先验（有后见污染） | **不能当先验用** |
| `baselines/out/live/*.jsonl` | B1/B2 在 **100 题全量**上的真实 LLM 预测，每行自证 mode/model/version/graph/branch | **可引用**（就是 `metrics_all_live.md` 的来源）；缓存入库可零花费复跑 |
| `baselines/out/pilot_19q/` | 19 题 pilot 的归档输出（全量会覆盖 `out/live/` 同名文件） | 历史留证，数字只作方向 |
| `baselines/out/stub/` | 100 题上的 stub 预测 | **没有科学含义**，只证明管线通 |
| `reports/metrics_all_live.md` | 全量 FR/FFR/MFR/UAR + 底噪对照（Newcombe 区间） | 唯一可引用口径，但见文件里的三条限定 |
| `metrics/score.py` | 指标实现 | 53 个手算用例通过 |

---

## 2. 四道闸门现状

| 闸门 | 判据 | 结果 |
|---|---|---|
| G0 数据可行性 | 探针四条都有判定 | a 受限(21.2%) / b 不达标 / c 不达标(130 实体) / d 部分 |
| G1 形式条件 | 闭包相等、互斥、并集 | 通过 |
| G2 算子确定性 | 两次指纹一致、边可追 | 通过 |
| G3 实现隔离+语义 | AST 零违规、500 行 × 2 个独立实现零分歧 | 通过 |

> 注意：`audit_night.py` 的 G0 未通过是**设计如此**（探针 b/c 两条 fail），所以整条命令退出码 1。
> 要看的是它写出的 `reports/night_audit_2026-11-17.md` 里逐闸门的判定，不要用退出码当结论。

---

## 3. 待 A 拍板（拦着后续一切）

| 编号 | 事 | 默认值（已按此跑通） | 推翻成本 |
|---|---|---|---|
| D1 | 130 实体够不够 120 题 | 降到 **100 题**（已生成） | 改题量 → 重跑 3 分钟 |
| D2 | MERGE 用合成对还是类级真实合并 | 合成 12 对 | 换类级合并 → 半天 |
| D3 | SPLIT 补集类命名 | 「非货运航空公司」 | 改字符串 → 1 分钟 |
| D4 | RESTRICT 时间维度（覆盖 21.2%） | 放弃时间，用属性收窄 | 补 P571 取数 → 1 晚 |
| D5 | 先验矩阵必须 A 独立填 | 草稿仅预演 | 无（纪律） |

---

## 4. 已知缺口（照实写，别在论文里藏）

1. **`branch` 字段已进预测行与 `docs/SCHEMA.md` 的字段表，但尚未经 A 确认**（D16）。代码与指标都按它配对，确认前不要把它当对外接口约定引用。
2. **B1 的 0 翻转是定义值，不是测量值**：语料冻结在 v1，两版喂给 LLM 的证据相同。它的作用是结构底噪，不是成绩。
3. **真实底噪 0.180，与效应只差一个边缘量**：同一 prompt 重采样，答案有 18% 会变（stable 子集 23.5%）；证据变化子集的翻转是 27.7%，差 +0.097、近似 p=0.042（未配对、偏乐观）。**「显著」这个词目前用不起。**
4. **一半配对根本没被算子触及**：500 个 v1↔v2 配对里有 251 个检索证据逐字相同（prompt 相同 → 缓存 → 必然同答案）。所以「refine FR=0.030」没有解读价值（94/100 的题没被动到）；主表 FR 也被这一半稀释。
5. **merge 分支的 v1 ≠ canonical v1**：主表表头必须标 `v1_mb`，否则跨分支不可比。
6. **refine 分支恒 0 翻转**：闭包语义下「该变的」不存在。它只能测误翻转（FFR），不能测漏翻转（MFR）。论文必须写，否则两张表打架。
7. **探针 a 的数据来自备用端点**（openlinksw），与 qlever 快照可能不同；引用时必须标来源。
8. **MFR 分母只有 25**（全库 `should=flip` 就 25 条，refine 为 0），这一行只能定性。

---

## 5. 下一步（按优先级，不需要再讨论就能做的）

1. **决定主结论怎么写**（最关键）：证据变化子集 0.277 vs 噪声 0.180，差 +0.097、p≈0.042（未配对、偏乐观）。三条路：
   ① 只报分层结果并如实说边缘（最诚实，但卖点变弱）；② 用 3 次采样投票/取中位数压噪声（约 +¥3，可能把噪声压到 0.05 以下，效应就立住了）；③ 换更稳的模型（`deepseek-chat` 非 flash）重跑。**这是 A 的判断，不是 S 的。**
2. **A 填先验**（`data/prior_20grid.template.json` → `prior_20grid.json`，别先看 `reports/t15_matrix.md`）→ 跑 `t15_matrix.py` → 不一致的格进 `decisions.md` 的 unexplained。
3. **D16：把 `branch` 写进 `docs/SCHEMA.md` 字段规范**（代码已按它配对，缺的是文档与 A 的同意）。
4. **B3**（LightRAG 或"带重排序的 B2"）——可在 B2 稳定后再加；不做就在论文里明确 descope。
5. **写 related work 半页**：材料已备好在 `docs/related_work_verify.md`，重点写「ΔSemantics 是前向重验证，我们是后向审计」。
6. **排期按 8 页含参考文献**（CCKS 中文限制，见 `docs/cfp_check.md`）——比原计划紧，摘要与方法节要压缩。
7. **（可做）把「内容翻转」与「拒答抖动」拆开报**：bfs2 的 69 条 FR 里 40 条是一侧拒答。论文里若只报 0.138，等于把「模型开始拒答」算成「答案变了」。

---

## 6. 怎么恢复（给下一个会话）

1. 读本文件 + `decisions.md`（尤其 D1–D5 是否已定）。
2. 跑 `python scripts/audit_night.py`，看四道闸门是否仍全绿；不绿说明代码被人改过，先查 diff。
3. 看 `git log`（若已建仓）与 `reports/` 最新一份，确认没有并行改动。
4. 不要重做已完成的事；**不要在没有 A 的先验时宣布 T1.5 结论**。

---

## 7. 2026-11-17 全天实际做了什么

**凌晨（00:20–01:35）**

| 时间 | 事 | 留痕 |
|---|---|---|
| 00:20–00:35 | 方案 + T1.0 探针（含备用端点绕限流） | `reports/t10_probe.md` |
| 00:35–00:45 | T1.2 类型 + T1.3 四算子 + G1/G2 | `reports/t12_schema.md`、`t13_ops.md` |
| 00:45–00:55 | T1.4 求解器 + G3 | `reports/t14_labels.md` |
| 00:55–01:20 | T2.1/T2.2 100 题 + T1.5 脚手架 | `data/questions_v1.json`、`t15_matrix.md` |
| 01:20–01:35 | 四个子代理并行（文献/会议/基线/指标）+ 复核 | `docs/related_work_verify.md`、`docs/cfp_check.md`、`baselines/`、`metrics/` |

**白天（验收整改 → pilot）**

| 提交 | 事 |
|---|---|
| `0f00efc` | as-found：夜间产物原样存档，先留证再改 |
| `70f25ab` | stage0：图指纹台账 + 基线输出 as-found 清单 |
| `a096a79` | stage1：撤回假闸门（回执曾写"全部通过"，实际 G0 不过）→ `INCIDENT_*.md` |
| `1b7f3d8` | stage2：结果溯源（每行补 mode/model/branch；`audit_results.py`） |
| `b3ef3c7` | stage4：文档对账（数字台账、声称台账、20 格改名、全文定位） |
| `5f09b5a` | harden：LLM 重试/错误体/effort/缓存 key；基线单题隔离 + 增量落盘 + resume |
| `a0891ce` | **live pilot**：`deepseek-flash` 19 题 × 20 格 = 380 行 0 错误，六条判据全过，C3 转 PARTIAL |
| `ae7aac9` | chore：清试跑临时文件 |

**13:15 之后**：状态复核（见提交 `review: ...`）——修 `score.py` 重复判定漏 branch、
把 README / numbers / claims_ledger / RESUME 从「基线是 stub」更新为「pilot 已跑通、全量未跑」。

**17:30–17:46 全量基线（三次跑动，见 `reports/INCIDENT_2026-11-17_resume_cache.md`）**

| 次 | 条件 | 结果 |
|---|---|---|
| 1 | `--full --resume`，4 workers | 1810 行：10 个 bfs2 cell 只有 81 行——**resume 把旧行写丢了**，作废 |
| 2 | 修 resume 后，6 workers | 2000 行、0 失败，但 **B1 FR=0.012**（6 条）：两个 cell 并发抢同一 prompt，缓存无锁 → 各调一次、拿回两个答案，负控破，作废 |
| 3 | 加缓存锁 + 原子写后，6 workers | 2000 行、0 失败、**9 秒全缓存**、B1 FR=0.000 → **采用** |

累计 460 次唯一调用、¥2.02。两组回归测试（resume 不丢行、并发只调一次）已进 `baselines/tests_smoke.py`。

**18:00–18:35 噪声底噪**

| 事 | 结果 |
|---|---|
| 设计：v1 独立跑两遍（每遍独立缓存），比较同一 prompt 的答案 | 噪声 FR **0.180（18/100）**、stable 子集 0.235（16/68） |
| 跑批：后台并发被环境的批量删除保护打断（锁文件反复 unlink 触发风控）→ 改前台逐格跑 | 12 个 cell 全部完成，472 次调用 / **¥1.44** |
| 顺带发现：主表 500 个配对里 **251 个证据没变**（prompt 相同 → 缓存 → 必然同答案） | 证据变化的 249 个配对才是有效样本，翻转 **0.277** |
| 结论 | 效应 − 噪声 = **+0.097**，近似 p=0.042（未配对、偏乐观）；**「显著」用不起**，新增 D17 交 A 判 |

**没做的**：B3、论文正文、任何对外提交。
