# 受控图谱变更下的多跳问答稳定性

在 Wikidata 航空子图上施加四类 **schema 级结构变更**（类型细化 / 关系收窄 / 实体合并 / 概念拆分），
用**确定性求解器**算出「变更后本该怎么答」，再看两条多跳问答基线的答案真的翻了多少——
以及这些翻转是不是只是模型自己的抖动。

> 一句话：**图变了，旧答案还成不成立？** 本文测的是「不成立」的比例，并把「应然」与「实测」的实现彻底分开，避免循环论证。

本科兴趣小组项目｜投稿定位：CCKS 2027 / CCL 2027 **全文**（两会均无独立短文类别，见 `docs/cfp_check.md`）

---

## 结论先行（2026-11-17 口径）

- **管线全通**：取图 → 类型 → 四算子 → 500 行应然标签 → 两条基线 2000 行真实调用 → 指标 → 噪声底噪，离线整链 3.3 秒可复跑。
- **主表**：B2（两跳有损检索）FR = 0.138（69/500），负控 B1 = 0.000。
- **但 0.138 不能直接当结论**：500 个 v1↔v2 配对里有 **251 个检索证据逐字未变**（prompt 相同 → 缓存 → 翻转必然为 0），把效应稀释了一半。
  只看证据真的变了的 **249 对**，翻转率是 **0.277**。
- **噪声底噪 0.180**（同一张 v1 图独立跑两遍，18/100 答案会变）。效应 − 噪声 = **+0.097**，近似 p=0.042（未配对，偏乐观）。
  所以现在能写的是「**约为噪声的 1.5 倍**」，**不能写「显著高于噪声」**。
- **G0（数据可行性）未通过**：四个探针里 b、c 两条 fail，d 部分通过。所有算子的合成成分都在 `docs/data_card.md` 与 `decisions.md` 里标注，不藏。

---

## 实验设计

| 步骤 | 做什么 | 产物 | 命令 |
|---|---|---|---|
| 1. 取图 | Wikidata 种子（中国 + 港澳台 + 日韩航司）→ 一跳 → 补 P31/P17/P279 → 修剪 → 繁简统一 | `data/graph_v1.json`（590 实体 / 1857 边 / 指纹 `d5935c6c56f97176`） | `scripts/fetch_subgraph.py`、`scripts/verify_subgraph.py` |
| 2. 定类型 | 建类型树，为四个算子选目标类，形式条件由脚本断言 | `data/schema.json`（118 类，深度 3） | `scripts/build_schema.py`、`scripts/verify_schema.py` |
| 3. 施加算子 | 四算子各生成一张 v2 图，边带 `id`/`why`，改动可逐条追溯 | `data/graph_v2_{refine,restrict,merge,split,all}.json` + merge 分支的基线 `graph_v1_mb.json` | `ops/apply_ops.py --all`、`scripts/verify_ops.py` |
| 4. 算应然标签 | `gold = Solve(Q, G)`，同一题在 v1/v2 上各解一次，差异即 `should` | `data/qa_v1.jsonl`（500 行 = 100 题 × 5 分支） | `labels/solver.py`、`scripts/verify_labels.py` |
| 5. 跑基线 | B1 负控、B2 有损检索，真实 LLM 全量 2000 行 | `baselines/out/live/*.jsonl` | `scripts/run_live.py --full` |
| 6. 算指标 | FR / FFR / MFR / UAR，配噪声底噪与分层 | `reports/metrics_all_live.md`、`reports/noise_floor.md` | `metrics/score.py`、`scripts/noise_floor.py` |

**四个算子**（每个都带限定词，见 `docs/claims_ledger.md`）：

| 算子 | 实例 | 必须带的前提 |
|---|---|---|
| `REFINE_TYPE` | 机场子树 → 最具体类型化（删 38 条冗余父类断言） | 原计划用「航空公司」，实测可迁移断言为 0，被迫换到机场 |
| `RESTRICT_REL` | 枢纽关系收窄为「枢纽位于中国」（有枢纽的航司 129 → 64） | **属性收窄，不是时间收窄**（P121 时间限定词覆盖仅 21%） |
| `MERGE_ENTITY` | 12 对**合成**重复节点合并回真实实体 | 输入是人工构造的，标签仍由求解器算 |
| `SPLIT_CONCEPT` | 航空公司 → {货运航空公司（真实 11）+ 非货运航空公司（补集 177）} | 负分支是**分析构造的补集类**，不是 Wikidata 类型 |

**方法论上最关键的一条**：标签不依赖对变更类型的语义判断，只依赖两张图上确定性查询结果的差异。
`solver.py` 与 `ops/`、`baselines/` 的实现完全隔离，由 AST 检查强制（`scripts/verify_labels.py`），
两者只共享同一份图数据。

---

## 主表（可引用）

真实 LLM 全量：`deepseek-flash`、temperature 0、seed 42、reasoning_effort high、20 格 × 100 题 = **2000 行、0 失败**、460 次唯一调用、**¥2.02**。

| 方法 | FR 答案翻转 | FFR 误翻转 | MFR 漏翻转 | UAR 不可答误答 |
|---|---|---|---|---|
| `b1_text`（负控） | 0.000 (n=500) | 0.000 (n=435) | 1.000 (n=25) † | 1.000 (n=40) |
| `bfs2`（两跳有损） | **0.138 (n=500)** | 0.113 (n=435) | 0.800 (n=25) † | 0.000 (n=40) |

† 分母仅 25，只作方向，不做显著性判断。B1 的 0 是**构造值**（语料冻结在 v1，v1/v2 prompt 逐字相同），不是成绩。

**分层后（这才是主结论的写法）**

| 层 | 配对数 | 翻转 | 翻转率 |
|---|---|---|---|
| 证据未变（prompt 逐字相同） | 251 | 0 | 0.000（缓存保证，不是模型稳定） |
| 证据变化（算子真的咬到检索到的边） | 249 | 69 | **0.277** |
| 噪声：同一 prompt 重采样（v1 跑两遍） | 100 | 18 | **0.180**（stable 子集 16/68 = 0.235） |

FR 的 69 条翻转里 **40 条是一侧拒答**（空串/`[]`），内容层面的翻转只有 29 条——两者必须分开报。

---

## 复现

**环境**：Python 3.10+，**无第三方依赖**（全部标准库）。真实基线需要 OpenAI 兼容端点的 key，写在 `baselines/.env`（已在 `.gitignore` 中）。

```bash
git clone <repo> && cd Macro-thought

# 离线整链：3.3 秒，不联网、不消耗 SPARQL 配额
python scripts/probe_t10.py           # T1.0 四探针（加 --with-a 才联网）
python scripts/build_schema.py        # 类型树
python ops/apply_ops.py --all         # 五份 v2 图
python labels/solver.py --smoke       # 应然标签
python scripts/audit_night.py         # 四道闸门 + 确定性复跑（G0 不过时退出码 1，属预期）

# 基线：全量 2000 行已在库内；命中 .cache_live 时 9 秒、零花费
cd baselines && cp .env.example .env  # 填 key；只读缓存时可留空
cd .. && python scripts/run_live.py --full --workers 6
python scripts/audit_results.py       # 每行自证 mode/model/version/graph/branch
python metrics/tests_smoke.py         # 指标 53 个手算用例
python baselines/tests_smoke.py       # 基线冒烟（含 resume 不丢行、并发缓存锁两组回归）
python scripts/noise_floor.py --analyze-only   # 噪声底噪 + 证据变/未变分层
```

`baselines/out/live/` 的 2000 行预测与 `baselines/.cache_live/` 的 460 条应答（含 usage/latency/prompt_sha1）均已入库，
所以指标报告可以在**不调用任何 API** 的情况下重算：

```bash
python metrics/score.py --qa data/qa_v1.jsonl --branch all --out /tmp/m.md \
  $(for m in b1_text bfs2; do for br in refine restrict merge split all; do for v in v1 v2; do \
      printf -- "--pred baselines/out/live/%s_%s_%s.jsonl " $m $br $v; done; done; done)
```

---

## 仓库结构

```
README.md                    本文件
LICENSE                      MIT
requirements.txt             无第三方依赖（仅声明标准库与 Python 版本）
decisions.md                 决策日志（D1–D17 + 未解释项 U1–U5），每条带依据与推翻条件
RESUME.md                    长程状态与恢复入口：现在能跑什么、缺什么、下一步
docs/
  data_card.md               数据卡：怎么建、字段、六条已知偏差
  SCHEMA.md                  三类产物的字段约定（图 / 题与标签 / 预测）
  numbers.md                 数字台账（唯一口径，每个数字带复现命令）
  claims_ledger.md           声称台账（能说什么、不能说什么）
  cfp_check.md               两会 CFP 核实（页数限制、有无短文类别）
  related_work_verify.md     八条相关工作的题名/出处核实
  fingerprints_2026-11-17.txt 七份图的指纹与 sha256
scripts/                     取图、探针、类型、出题、审计、底噪、真实跑批
ops/apply_ops.py             四算子 → v2 图
labels/solver.py             应然标签（禁止 import ops/、baselines/，AST 强制）
baselines/                   B1 朴素 RAG（负控）、B2 两跳有损检索、统一 LLM 接口
metrics/score.py             FR/FFR/MFR/UAR + Newcombe 区间 + 底噪对照
data/                        图（v1 冻结 + v2×5）、schema、题目、500 行标签、探针与底噪数据
reports/                     各阶段验收记录、指标、事故记录（含一次闸门误判的复盘）
archive/wn18rr-repro/        第一阶段：WN18RR 上 TransE/RotatE 的复现（背景工作，非本文实验）
```

---

## 闸门与状态

| 阶段 | 状态 |
|---|---|
| T1.0 四探针 | **不通过**：a 受限(21.2%)、b fail（3 对且全假阳性）、c fail（590/590/**130** 可用实体）、d partial |
| T1.1 取图 | 通过：六项验收 + 指纹可复现 |
| T1.2 类型清单 | 形式通过（闭包相等、互斥、并集由脚本断言），语义降级（REFINE 从航司换到机场） |
| T1.3 四算子 | 形式通过：七份图连跑两次指纹一致，边可逐条追溯 |
| T1.4 求解器 | 通过：500 行 × 2 个独立实现零分歧 |
| T1.5 应然矩阵 | **不成立**：只跑了 S 的草稿先验，A 的正式先验待填（`data/prior_20grid.json`） |
| T2.1/T2.2 题集 | 完成：100 题（count 32 / set 24 / bool 16 / hop2 28） |
| B1/B2 基线 | 全量跑通，负控成立 |
| B3 LightRAG | **未实现**，所以「三个基线」不成立 |

`python scripts/audit_night.py` 的退出码 1 是设计如此（G0 探针 fail），要看它写出的报告里逐闸门判定，不要用退出码当结论。

---

## 已知局限（引用时必须带）

1. **效应只比噪声高一个边缘量**：0.277 vs 0.180，+0.097、近似 p=0.042，未配对、两边题重叠，p 值偏乐观。
2. **一半配对没被算子触及**：251/500 的检索证据逐字相同，`refine` 分支 94/100 未被动到，所以「refine FR=0.030」没有解读价值。
3. **refine 分支恒 0 翻转**：闭包语义下「该变的」不存在，它只能测误翻转，不能测漏翻转。两张表必须一起看。
4. **MFR 分母只有 25**（`should=flip` 全库 25 条，refine 为 0），只能定性。
5. **merge 分支的 v1 ≠ canonical v1**：它是 `graph_v1_mb.json`（v1 + 12 个合成重复节点），跨分支比较必须标 `v1_mb`。
6. **三个算子带合成成分**：MERGE 输入人工构造、RESTRICT 是属性收窄、SPLIT 负分支是补集类。
7. **数据规模偏小**：130 个「有 ≥2 条类型化关系」的实体，每格 20 题，单格结论脆弱。
8. **探针 a 的数据来自备用端点**（openlinksw），与 qlever 快照可能不同，引用须标来源。

更完整的「不能说什么」见 `docs/claims_ledger.md`。

---

## 先读这两份

- [`docs/claims_ledger.md`](docs/claims_ledger.md) —— 现在能声称什么、不能声称什么（写摘要/汇报前逐条对照）
- [`docs/numbers.md`](docs/numbers.md) —— 所有数字的唯一口径，每个数字带复现命令

需要人拍板的事在 [`decisions.md`](decisions.md)（D1–D5、D17 仍待定）；长程恢复入口是 [`RESUME.md`](RESUME.md)。

---

## 数据来源与许可

- 图数据取自 Wikidata（**CC0 1.0**），经 `qlever.dev` 的 Wikidata 端点构建；子图沿用 CC0。
- 本仓库代码与文档采用 **MIT License**（见 `LICENSE`）。
- 运行时不依赖任何第三方 Python 包；真实基线调用的是 OpenAI 兼容接口，密钥不入库。
- `archive/wn18rr-repro/` 为项目第一阶段的复现工作（WN18RR 上 TransE/RotatE），保留作背景与工程能力证明，**不属于本文实验**。

## 协作方式

三人兴趣小组（数据与变更 / 基线与实验 / 评测与写作）+ AI 辅助实现。
**代码可由工具生成，判断不能**：先验矩阵、闸门判定、合成成分是否可接受、主结论怎么写，均记在 `decisions.md` 里由人拍板；
实现与验收分离，验收方复跑命令看数字，不读文字信数字。
