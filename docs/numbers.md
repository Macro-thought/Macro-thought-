# 数字台账（唯一口径来源）

规则：**任何文档、汇报、论文里出现的数字，都必须能在本表找到同名的「定义 + 复现命令」。**
对不上的，以本表为准；本表也没有的，先补进本表再用。

更新：2026-11-17　｜　维护：S

---

## 一、图（冻结，改动即让 500 行标签失效）

| 数字 | 值 | 定义 | 复现 |
|---|---|---|---|
| 图规模 | **590 实体 / 1857 边** | `graph_v1.json` 的 `len(entities)` / `len(edges)` | `python scripts/verify_subgraph.py` |
| 图指纹 | `d5935c6c56f97176` | 实体 id 集合 + 边集合的 sha1 前 16 位 | 同上 |
| 种子航司 | 216 请求 / **184 有中文名** | P31⊆Q46970 且 P17∈{中国,港澳台,日韩} | `python scripts/fetch_subgraph.py` 首段输出 |
| 丢弃 | 无中文名 **71**、孤儿 **1** | 见 `docs/data_card.md` §一 | 同上 |
| 繁简 | 可疑 **182** 条，实际转换 **65** 条 | 回退到 zh/zh-hant/zh-tw 的标签数 / zhconv 真正改动数 | 同上 |

七份图的规模、退休边与指纹见 `docs/fingerprints_2026-11-17.txt`（含文件 sha256）。

## 二、类型树

| 数字 | 值 | 定义 | 复现 |
|---|---|---|---|
| 类数 | **118** | `schema.json` 的 `meta.n_classes`（同一类可被多实体共用） | `python scripts/verify_schema.py` |
| 最大深度 | 3 | 深度分布 0/1/2/3 = 59/44/13/2 | 同上 |
| 多类型实体 | 177 | 拥有 >1 个 P31 的实体数 | 同上 |

> 口径提醒：`t10_probe.md` 里的「116 个类有实例断言」与这里的 118 是**两个指标**——前者只数"至少有一个实例的类"，后者含无实例的中间类。引用时写清是哪个。

## 三、题集与标签

| 数字 | 值 | 定义 | 复现 |
|---|---|---|---|
| 题数 | **100** | `questions_v1.json` 的 `questions` 长度 | `python -c "import json;print(len(json.load(open('data/questions_v1.json',encoding='utf-8'))['questions']))"` |
| 题形配额 | count 32 / set 24 / bool 16 / hop2 28 | 按题形计的题数 | 同上 |
| 标签行数 | **500** = 100 题 × 5 分支 | `qa_v1.jsonl` 的 JSON 记录数（文件末尾无换行，`wc -l` 会少 1） | `python scripts/verify_labels.py` |
| 应然分布 | **stable 435 / flip 25 / unanswerable 40** | 每行的 `should` 字段 | `python -c "import json,collections;print(collections.Counter(json.loads(l)['should'] for l in open('data/qa_v1.jsonl',encoding='utf-8') if l.strip()))"` |

分分支的 `stable/flip/unanswerable`：

| 分支 | stable | flip | unanswerable |
|---|---|---|---|
| refine | 100 | **0** | 0 |
| restrict | 77 | 3 | 20 |
| merge | 92 | 8 | 0 |
| split | 98 | 2 | 0 |
| all | 68 | 12 | 20 |

> **这张表是当前设计最大的统计软肋**：全库只有 25 条「应翻」，refine 分支为 0。
> 因此 **MFR（漏翻转率）在任何单个分支上分母都是 0–12，不可解读**；FFR 也只能描述、不能做显著性检验。
> 论文里必须按格标 n，n<10 打 †，且正文不得解读这些格。

> 口径提醒：`t14_labels.md` 的标题曾写「19 题 × 5 分支」，那是 `qa_smoke.jsonl`（95 行）的规模；**正式数据是 500 行**。标题已由生成器修正。

## 四、基线

| 数字 | 值 | 定义 | 复现 |
|---|---|---|---|
| 基线个数 | **2**（B1 朴素 RAG、B2 两跳 BFS） | B3/LightRAG **未实现** | `ls baselines/*.py` |
| stub 输出 | `baselines/out/stub/` 下 **20 个文件** | 5 分支 × 2 版本 × 2 基线 | `python scripts/audit_results.py` |
| legacy 输出 | `baselines/out/` 根目录 **24 个文件** | 11-17 凌晨的 as-found 产物，**全部 stub 且缺 mode** | 同上（默认跳过判定） |
| **全量基线（可引用）** | **20 格 × 100 题 = 2000 行，0 失败、0 错误行** | `baselines/out/live/`，题集 `questions_v1.json`；B1 每格 100/100 作答，B2 v1 42.4% / v2 41.2% | `python scripts/audit_results.py`（退出码 0）；`baselines/out/live/_run_config.json` |
| 真实 LLM 调用（累计） | **460 次唯一调用** | 缓存 460 条 `mode=live`（另 1 个文件是 B1 语料快照）；pilot 65 次 + 全量新增 395 次 | `python -c "import json,glob;print(sum(1 for f in glob.glob('baselines/.cache_live/*.json') if isinstance(json.load(open(f,encoding='utf-8')),dict)))"` |
| 累计成本 | **¥2.02** | input 280,166 / output 183,070 token（`reasoning_effort=high` 的推理 token 计入 completion） | `_run_config.json` 的 usage 汇总 |
| pilot 成本 / 延迟 | ¥0.32；p50 **1.42s** / p95 **10.92s** | 65 次唯一调用，超时 0、429 0、fatal 0 | `reports/pilot_live_2026-11-17.md` 第三节 |
| live 输出文件 | `baselines/out/live/` 下 **23 个** = 21 个预测 jsonl（20 格 + 1 个定向补测 `bfs2_all_v2_uar`）+ `_run_config.json` + `_events.jsonl`；另有归档 `out/pilot_19q/` **23 个** | 5 分支 × 2 版本 × 2 方法 | `ls baselines/out/live`；`python scripts/audit_results.py` |

### 四之二、指标（全量，2026-11-17 17:45 口径）

| 指标 | b1_text（负控） | bfs2（两跳有损） | 定义 |
|---|---|---|---|
| FR 答案翻转率 | **0.000（0/500）** | **0.138（69/500）** | 两版都有预测的题里答案不同的比例 |
| FFR 误翻转率 | 0.000（0/435） | **0.113（49/435）** | `should=stable` 的题里答案变了的比例 |
| MFR 漏翻转率 | 1.000（25/25） | **0.800（20/25）** | `should=flip` 的题里答案没变的比例（**分母仅 25**） |
| UAR 不可答误答率 | 1.000（40/40） | **0.000（0/40）** | `should=unanswerable` 时仍给出非空答案的比例 |
| FR 差（Δ） | — | **+0.138，95% CI [+0.109, +0.171]，p<0.0001** | Newcombe 混合法差值区间 |

> **三个必须一起说的限定**：
> 1. **B1 的 0 是构造值**：语料冻结在 v1，v1/v2 是同一个 prompt，答案由缓存保证相同。它只能当"结构底噪"，不能用来算显著性；真实噪声要另跑 `noise_floor`（未做）。
> 2. **bfs2 的翻转里有一半是"拒答抖动"**：FR 的 69 条翻转中 **40 条**是一侧未作答、FFR 的 49 条中 **21 条**同理。只算内容层面的翻转，FR 是 29/500。
> 3. **MFR 分母只有 25**（全库 `should=flip` 就 25 条，refine 分支为 0），该行数字只能定性说明方向，不得做显著性判断。

复现（**别用 `--pred baselines/out/live/*.jsonl`**：会把定向补测 `_uar` 文件也算进去，造成同分支重复行）：

```bash
python metrics/score.py --qa data/qa_v1.jsonl --branch all --out reports/metrics_all_live.md \
  $(for m in b1_text bfs2; do for br in refine restrict merge split all; do for v in v1 v2; do \
      printf -- "--pred baselines/out/live/%s_%s_%s.jsonl " $m $br $v; done; done; done)
```

`data/prior_20grid.json` 未填，第 5 节的 Δ 只对 `b1_text` 底噪，不对先验。

### 四之三、噪声底噪与分层（2026-11-17 18:35 口径）

| 数字 | 值 | 定义 | 复现 |
|---|---|---|---|
| 噪声 FR | **0.180（18/100）** | B2 在**未变更的 v1 图**上独立跑两遍（每遍独立缓存），答案不同的比例 | `python scripts/noise_floor.py --analyze-only` |
| 噪声 FR（stable 子集） | **0.235（16/68）** | 同上，只在 `should=stable` 的题上 —— 这是 FFR 的底噪 | 同上 |
| 分层：证据未变 | **0/251 = 0.000** | 主表 500 个 v1↔v2 配对里，检索到的边逐字相同的那些 → prompt 相同 → 缓存保证同答案 | 同上，第四节 |
| 分层：证据变化 | **69/249 = 0.277** | 证据真的变了的配对，翻转率 | 同上 |
| 效应 − 噪声 | **+0.097**，近似 z=2.03、p=0.042 | 未配对、两边题重叠，p 偏乐观，只能当量级参考 | 同上 |
| 噪声成本 | **472 次调用 / ¥1.44** | 缓存 `baselines/.cache_noise/`（**不入库**，可重跑） | — |

> **这一节改了主结论的写法**：`FR=0.138` 是 500 个配对的混合平均，其中一半配对根本没换 prompt，
> 必然为 0，把效应稀释了一半。要么报「证据变化子集 0.277 vs 噪声 0.180」，要么同时报两个数。
> 单独写 0.138 会被审稿人当成噪声水平的效应。

## 五、已知不可复现的数字（引用时必须带限定）

| 数字 | 状态 | 说明 |
|---|---|---|
| P121 时间限定词覆盖率 **21.2%** | **管线外单次探测** | 不在 `probe_t10.py` 的输出里（该脚本的 a 项是 `unverified`）。数值来自一次独立的手工查询，未落盘查询原文与快照时间。**没有决策依赖它**（D4 已放弃时间收窄），引用时写「单次探测，未复现」。 |
| `0.316`（split 分支 B1/B2 的 FR 差） | **作废** | 来自 `reports/stub/metrics_split_smoke.md`，19 行冒烟、stub 模式、6 次翻转中 5 次是"空答翻转"。**不得引用**。 |
| pilot 的 FR/FFR/MFR/UAR 任何值 | **历史，只作方向** | 19 题、各格 n=0–19。全量口径见 `reports/metrics_all_live.md`；pilot 输出已归档 `baselines/out/pilot_19q/`。引用 pilot 数字必须写 n 与「pilot」二字。 |
| 「全量首跑」的任何数字 | **作废** | 第一次全量跑动（`--resume`，4 workers）bfs2 只有 81 行/格、第二次 B1 FR=0.012。两次都因代码缺陷作废，见 `reports/INCIDENT_2026-11-17_resume_cache.md`。只认第三次（2000 行、B1 FR=0.000）。 |
| 「1000 次重算零分歧」 | **口径不明** | 取自 `t14_labels.md` 的表述，未说明是 500 行 × 2 版。引用时改为「500 行 × 2 个独立实现」或直接给 `verify_labels.py` 的输出。 |

## 六、仓库规模

| 数字 | 值 | 定义 |
|---|---|---|
| 入库文件 | **534** = 73 个代码/文档/数据 + 461 条 LLM 应答缓存 | `git ls-files \| wc -l`（不含 `baselines/out/`、`data/cache/`、`.env`） |
| 缓存体积 | `baselines/.cache_live/` **2.2 MB** | 461 个文件 = 460 条 live 应答 + 1 个 B1 语料快照（`corpus_graph_v1_*.json`，即 B1 读图方式为「v1 语料固定」的证据）；全量重跑 9 秒、零花费靠它 |

引用"文件数"时必须说明是哪个口径。
