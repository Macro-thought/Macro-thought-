# 翻转指标报告

- 生成时间：2026-11-17 17:45
- qa：`data/qa_smoke.jsonl`（95 题，19 个不同 qid，qid 在分支内唯一）
- pred：`baselines/out/pilot_19q/b1_text_refine_v1.jsonl`、`baselines/out/pilot_19q/b1_text_refine_v2.jsonl`、`baselines/out/pilot_19q/b1_text_restrict_v1.jsonl`、`baselines/out/pilot_19q/b1_text_restrict_v2.jsonl`、`baselines/out/pilot_19q/b1_text_merge_v1.jsonl`、`baselines/out/pilot_19q/b1_text_merge_v2.jsonl`、`baselines/out/pilot_19q/b1_text_split_v1.jsonl`、`baselines/out/pilot_19q/b1_text_split_v2.jsonl`、`baselines/out/pilot_19q/b1_text_all_v1.jsonl`、`baselines/out/pilot_19q/b1_text_all_v2.jsonl`、`baselines/out/pilot_19q/bfs2_refine_v1.jsonl`、`baselines/out/pilot_19q/bfs2_refine_v2.jsonl`、`baselines/out/pilot_19q/bfs2_restrict_v1.jsonl`、`baselines/out/pilot_19q/bfs2_restrict_v2.jsonl`、`baselines/out/pilot_19q/bfs2_merge_v1.jsonl`、`baselines/out/pilot_19q/bfs2_merge_v2.jsonl`、`baselines/out/pilot_19q/bfs2_split_v1.jsonl`、`baselines/out/pilot_19q/bfs2_split_v2.jsonl`、`baselines/out/pilot_19q/bfs2_all_v1.jsonl`、`baselines/out/pilot_19q/bfs2_all_v2.jsonl`
- branch 过滤：`all`
- 方法：b1_text, bfs2

> 格子格式 `指标值 (n=分母)`。n 是该格有效样本数；`—` 表示 n=0，此时数值无意义，不要解读。
> `†` 表示 n < 10：样本太少，区间宽度足以覆盖任何真实差异，只作参考。

## 0. 预测的分支归属

一个方法通常只在一张 v2 图上跑过，而 qa 的 qid 在各分支里重复，所以先把预测解析到唯一分支再配对。解析依据如下：

| method | 落入分支（行数） | 解析依据 | 丢弃行 | 图名冲突 |
|---|---|---|---|---|
| `b1_text` | all=38、merge=38、refine=38、restrict=38、split=38 | 无 | 0 | 0 |
| `bfs2` | all=38、merge=38、refine=38、restrict=38、split=38 | 无 | 0 | 0 |

## 1. FR 答案翻转率

两版都有预测的题里，答案不同的比例。整体抖动水平，不是好坏指标。

| method | refine | restrict | merge | split | all | 总计 |
|---|---|---|---|---|---|---|
| `b1_text` | 0.000 (n=19) | 0.000 (n=19) | 0.000 (n=19) | 0.000 (n=19) | 0.000 (n=19) | 0.000 (n=95) |
| `bfs2` | 0.053 (n=19) | 0.158 (n=19) | 0.105 (n=19) | 0.211 (n=19) | 0.316 (n=19) | 0.168 (n=95) |

## 2. FFR 误翻转率（核心）

should=stable 且两版都有预测的题里，答案变了的比例。越低越好：改图不该让本该稳定的题翻。

| method | refine | restrict | merge | split | all | 总计 |
|---|---|---|---|---|---|---|
| `b1_text` | 0.000 (n=19) | 0.000 (n=14) | 0.000 (n=15) | 0.000 (n=18) | 0.000 (n=10) | 0.000 (n=76) |
| `bfs2` | 0.053 (n=19) | 0.071 (n=14) | 0.000 (n=15) | 0.167 (n=18) | 0.200 (n=10) | 0.092 (n=76) |

## 3. MFR 漏翻转率

should=flip 且两版都有预测的题里，答案没变的比例。越低越好：该翻的没翻，说明扰动没被捕捉到。

| method | refine | restrict | merge | split | all | 总计 |
|---|---|---|---|---|---|---|
| `b1_text` | — (n=0) | 1.000 (n=3) † | 1.000 (n=4) † | 1.000 (n=1) † | 1.000 (n=7) † | 1.000 (n=15) |
| `bfs2` | — (n=0) | 1.000 (n=3) † | 0.500 (n=4) † | 0.000 (n=1) † | 0.714 (n=7) † | 0.667 (n=15) |

## 4. UAR 不可答误答率

should=unanswerable 且 v2 有预测的题里，v2 仍给出非空答案的比例。越低越好。

| method | refine | restrict | merge | split | all | 总计 |
|---|---|---|---|---|---|---|
| `b1_text` | — (n=0) | 1.000 (n=2) † | — (n=0) | — (n=0) | 1.000 (n=2) † | 1.000 (n=4) † |
| `bfs2` | — (n=0) | 0.000 (n=2) † | — (n=0) | — (n=0) | 0.000 (n=2) † | 0.000 (n=4) † |

## 5. 噪声底噪对照（FR vs `b1_text`）

把文本基线在 v1/v2 上的 FR 当底噪：不依赖图结构的方法，单换一张图也会让一部分答案抖动。只有明显高于底噪的 FR 才算图结构带来的信号。

底噪：`b1_text` FR = 0.000 (n=95，0/95)

| method | FR (n) | 底噪 FR (n) | Δ = FR − 底噪 | 95% CI（Newcombe） | z 检验 p | 判定 |
|---|---|---|---|---|---|---|
| `bfs2` | 0.168 (n=95) | 0.000 (n=95) | +0.168 | [+0.095, +0.256] | <0.0001 | 差异显著 |

注：区间是**差值**的区间（Newcombe 混合法），不是两个单侧 Wilson 区间；p 值来自未做连续性校正的两比例 z 检验。区间跨 0 且 p≥0.05 时，只能说「没看到差异」，不能说「两者一样」。

## 脚注：缺预测明细（不静默丢弃）

缺预测的题已从对应指标的分母剔除，下面是剔除量（按 method 总计）。若某格 missing 占比很高，该格的指标实际只代表一小撮题，不能外推。

- `b1_text` — FR:无缺失；FFR:无缺失；MFR:无缺失；UAR:无缺失
- `bfs2` — FR:其中空答翻转=10；FFR:其中空答翻转=2；MFR:无缺失；UAR:无缺失

空答提示：以下方法的 FR 里，有翻转是由「一侧未作答（空串/[]）」造成的，不是内容层面的变化：`bfs2` 10/16。

---

指标定义与「为什么不用 accuracy」见 `metrics/README.md`；自检见 `python metrics/tests_smoke.py`。
