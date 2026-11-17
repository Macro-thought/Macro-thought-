# T1.5 应然矩阵：先验 vs 实测

数据：`data/qa_v1.jsonl`（500 行 = 100 题 × 5 分支）　｜　生成：`scripts/t15_matrix.py`

> **先验未确认：只输出实测，不输出「一致/不一致」。**请 A 填 `data/prior_20grid.json` 并在 `meta.confirmed_by` 签名（见 decisions.md D5）。

## 实测（stable / flip / unanswerable）

| 分支 | count | set | bool | hop2 |
|---|---|---|---|---|
| refine | 32/0/0 | 24/0/0 | 16/0/0 | 28/0/0 |
| restrict | 29/1/2 | 19/0/5 | 16/0/0 | 13/2/13 |
| merge | 25/7/0 | 23/1/0 | 16/0/0 | 28/0/0 |
| split | 30/2/0 | 24/0/0 | 16/0/0 | 28/0/0 |
| all | 21/9/2 | 18/1/5 | 16/0/0 | 13/2/13 |

## 对照

先验未填或未确认，跳过对照。填法见 `data/prior_20grid.template.json`。
