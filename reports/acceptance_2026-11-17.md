# 竣工验收记录（2026-11-17）

复核：A（待签）　｜　执行：S　｜　依据：`C:\Users\MECHREVO\.workbuddy\plans\blazing-nebula-tesla-ETwNpKRH.md`

## 结论先行

**整改未完成。** 代码与文档层面的四项已通过，但 **P0-2（基线是 stub）未解决**——本机没有 LLM API key，真实数据一行都没有产出。
按整改计划事先写定的降级规则：「API key 不到 → 只做文档整改，P0 标未解决，终验判 FAIL 并顺延一天，**不得用 stub 顶替**」。所以本记录判 **FAIL（部分完成）**。

---

## 一、逐条验收

| 代号 | 判据 | 结果 | 证据 |
|---|---|---|---|
| C0 冻结留证 | git 已初始化、as-found 提交、指纹台账、基线清单 | **通过** | 4 个提交；`docs/fingerprints_2026-11-17.txt`；`baselines/OUT_MANIFEST.md` |
| C1 撤回假闸门 | 新回执不含"闸门总判定：全部通过"；重跑退出码 1；图文件不被时间戳弄脏 | **通过** | `grep -c '闸门总判定：全部通过'` = 0（as-found 存档中 = 1）；`audit_night.py` 退出码 1；`git status --porcelain data/` 为空 |
| C2 结果溯源 | 每行有 mode/model/branch；新输出过 `audit_results.py` | **通过** | `baselines/out/stub/` 20 个文件全部 `mode=stub, model=stub`；`audit_results.py` 退出码 0 |
| C3 真 LLM 小样本 | pilot 非空作答率 ≥50%，B1 FR=0.000 | **通过**（17:46 补记：pilot 六项全过；全量 2000 行 0 失败，B1 FR=0.000、bfs2 FR=0.138） | `reports/pilot_live_2026-11-17.md`；`reports/metrics_all_live.md`；`reports/INCIDENT_2026-11-17_resume_cache.md` |
| C4 文档对账 | 数字有台账；声称有分级；短文改全文；20 格改名 | **通过** | `docs/numbers.md`、`docs/claims_ledger.md`、`README.md`、`prior_20grid` |

## 二、这次改了什么（四个提交）

```
1b7f3d8 stage2: 结果溯源
a096a79 stage1: 撤回假闸门
70f25ab stage0: 冻结留证
0f00efc as-found: 夜间推进产物原样存档
```

| 文件 | 改动 |
|---|---|
| `scripts/audit_night.py` | 新增 `g0_verdict()` 读 `probe_t10.json` 的 verdicts；`gate_ok` 改为「G0 四项全 pass + G1–G3 退出码 0」；不通过时退出码 1，报告固定输出"G0 不通过 + 按 D1/D2/D4 缩范围" |
| `ops/apply_ops.py` | `built_at` 改为「指纹不变则沿用旧值」，解决每次审计都让 7 份图变脏 |
| `baselines/llm.py` | 新增 `mode_name()` / `model_name()` |
| `baselines/b1_text.py`、`b2_bfs.py` | 输出行补 `mode/model/branch`；新增 `--version` / `--branch`；默认输出改为 `out/stub/` 或 `out/live/`，文件名带分支 |
| `scripts/audit_results.py` | **新增**。按「文件」聚合检查 mode/model/version/graph/branch 一致性，legacy 目录默认跳过、`--strict` 才算失败 |
| `data/prior_15grid.template.json` → `prior_20grid.template.json` | 20 格改名，`t15_matrix.py` 路径同步；**先验未填时不再输出"一致/不一致"** |
| `reports/night_audit_2026-11-17.md` | 重新生成，总判定改为「未通过（G0 数据可行性）」 |
| `reports/night_audit_2026-11-17_asfound.md` | **新增**：原回执原样存档（含那句错误结论），作为事故证据 |
| `reports/INCIDENT_2026-11-17.md` | **新增**：事故根因、影响面、处置、纪律 |
| `reports/stub/` | `metrics_split_smoke.{md,json}` 移入，标注数字不得引用 |
| `docs/numbers.md` | **新增**：所有数字的唯一定义与复现命令 |
| `docs/claims_ledger.md` | **新增**：能声称 / 不能声称 / 必须带限定词的三句 / 审稿人最可能问的三问 |
| `README.md` | 短文→全文；三基线→两基线；补 T1.5 不成立、B3 未实现、闸门现状；三条工程纪律 |
| `baselines/OUT_MANIFEST.md` | **新增**：24 个 legacy 输出的行数/mode/version/graph/sha256 |

## 三、验收中新发现的问题（原计划没预料到）

| # | 发现 | 严重度 | 处置 |
|---|---|---|---|
| 1 | **应然标签的统计功效严重不足**：全库 500 行里 `should=flip` 只有 **25 条**，refine 分支为 **0**。MFR 在单格上的分母是 0–12，任何数值都不可解读 | **高** | 已写进 `docs/numbers.md` 第三节与 `claims_ledger` 的"不能声称"；**修法需改题集设计，不在本次范围** |
| 2 | B1 的 v1/v2 输出**字节完全相同**（如 all 分支两者都是 `40231526431c…`） | 中 | 这是负控的设计意图（B1 不读图），但必须写进方法节，否则会被当成 bug。已记入 claims ledger 第四节的答辩准备 |
| 3 | `b1_*_v2.jsonl` 有 **5 个**把 version 写成 v1（不是初步盘点说的 8 个） | 中 | 已精确计数并写进 `OUT_MANIFEST.md`；新输出已修 |
| 4 | `reports/` 下 6 份报告都是生成物，手改会被覆盖 | 中 | 写入 README 工程纪律第 1 条；本次所有文案修改都落在生成器或新增文件里 |

## 四、仍未解决（按优先级）

| 优先级 | 事项 | 谁来解 | 解除条件 |
|---|---|---|---|
| **P0** | 真实 LLM 基线 | 组内（需 key + 预算 50–150 元） | **已于 17:46 解决**：全量 2000 行 / 460 次调用 / ¥2.02，`audit_results.py` 退出码 0，B1 FR=0.000 |
| **P0** | 统计功效：25 条 should=flip 撑不起 MFR | A 拍板 | 扩题或改题集设计，使每分支 flip ≥10；改后必须重算 qa 并更新全部指纹 |
| P1 | T1.5 正式先验 | A | 填 `data/prior_20grid.json` 并 `confirmed_by` 签名，**commit 时间须早于对照运行** |
| P1 | G0 数据可行性 3 项 fail | 全组 | 扩种子到东南亚或换领域；或接受降级并在论文 Limitations 写死 |
| P2 | B3 / LightRAG 缺失 | 全组 | 决定做（3–5 天）或明确 descope 只写两个基线 |
| P2 | 探针 a 的 21.2% 不可复现 | — | 不修，已在 `docs/numbers.md` 第五节标"单次探测" |

## 五、下一步（建议顺序）

1. **拿到 key，跑 10 题 pilot**（`--live`），先看非空作答率。这一步决定后面 1000 次调用值不值得花。
2. pilot 通过后按分支拆 5 个进程跑 B2，B1 单进程；输出直接落 `out/live/`。
3. 跑 `python scripts/audit_results.py`，不过就先修溯源再算指标。
4. A 填先验（单独 commit），再跑 `t15_matrix.py`。
5. 上面都过了，再谈写论文——现在写正文等于给 stub 数字编故事。

## 六、签字

- 执行 S：已完成 C0/C1/C2/C4，C3 因缺 key 未执行
- 复核 A：____________　日期：________
- 复核对本次判定的意见：________________________________

---

## 七、补记（当日 13:20，key 到位后）

C3 的条件在 13:12 满足，故本记录的结论由 **FAIL（部分完成）** 上调为 **PARTIAL（pilot 通过、全量未跑）**：

| 项 | 补记 |
|---|---|
| C3 | **PARTIAL → 满足 pilot 判据**：`deepseek-flash`、19 题 × 5 分支 × 2 版本 × 2 方法 = 380 行、0 错误、¥0.32；六条判据全过（`reports/pilot_live_2026-11-17.md`）。**全量与噪声底噪仍未跑**，故不判 PASS |
| 文档 | README / `docs/numbers.md` / `docs/claims_ledger.md` / `RESUME.md` 四处「基线是 stub / 零真实调用」的表述已失效，本次一并订正（否则仓库自相矛盾） |
| 代码 | `metrics/score.py` 的「重复行」判定漏了 branch：跨分支同 qid 被误报成 304 行重复（实际 0 重复）。已改 key 为 `method+branch+qid+version`；重跑 `pilot_metrics.md`，四类指标数值**一字未变**，说明只是报告层误报，不影响已有结论 |
| 仓库 | 工作区干净（`git status` 空），共 137 个入库文件 = 71 代码/文档/数据 + 66 条 pilot 应答缓存（`.cache_live/` 有意入库，用于零花费复跑；已确认不含 key） |

**仍未解决的 P0/P1 与第四节相同**：全量基线、统计功效（25 条 flip）、正式先验、G0 三项 fail、B3。

---

## 八、二次补记（当日 17:46，全量基线跑完）

| 项 | 补记 |
|---|---|
| C3 | **PARTIAL → PASS**：20 格 × 100 题 = 2000 行、0 失败、0 错误行；累计 460 次唯一调用、¥2.02；`audit_results.py` 退出码 0 |
| 主表 | `reports/metrics_all_live.md`：B1 FR=0.000 / FFR=0.000；bfs2 FR=0.138（69/500）、FFR=0.113（49/435）、MFR=0.800（20/25）、UAR=0.000（0/40） |
| 事故 | 首跑暴露两个缺陷，前两次跑动全部作废：① `--resume` 把旧行写丢（10 个 cell 只有 81 行）；② 缓存 read-then-write 无锁 + 非原子写，B1 的 v1/v2 并发抢同一 prompt → 6 条翻转、负控破。均已修 + 两组回归测试，见 `INCIDENT_2026-11-17_resume_cache.md` |
| 仍未解决 | 噪声底噪（B1 的 0 是构造值，Δ 与 p 值仍需实测底噪）、统计功效（25 条 flip）、A 的正式先验、G0 三项 fail、B3 |
