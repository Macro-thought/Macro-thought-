# SCHEMA.md — 中间产物字段约定

本文件描述仓库里三类产物的**实际**字段。它们被多个脚本读写，改动会同时打断标签、基线与指标三条链，
所以规则是：**只允许在末尾加字段；改含义或删字段必须先开会，并在文末「变更记录」登记。**

> 与最初任务书里的接口约定（`repo-init/SCHEMA.md`，未入库）的差异：图从 `graph.jsonl` 改成单文件 `graph_v1.json` + `graph_v2_*.json`
> （需要 `meta` 与 `retired_edges`，单文件更好审计）；`qa` 增加了 `branch`、`shape`、`template`、`query`；
> `pred` 增加了 `branch` 与 `meta`。差异的原因写在每次变更的「为什么」里。

---

## 文件 1：`data/graph_v1.json` / `data/graph_v2_*.json` — 图

```json
{
  "meta": {"version": "v1", "built_at": "...", "endpoint": "...", "n_entities": 590, "n_edges": 1857,
           "idempotent_hash": "d5935c6c56f97176", "...": "..."},
  "entities": [{"id": "Q123", "label_zh": "…", "label_en": "…", "lang_source": "zh-hans",
                "type": "航空公司", "type_qids": ["Q46970"], "country": "Q148",
                "aliases": [], "is_seed": true}],
  "edges": [{"h": "Q123", "r": "P113", "t": "Q456", "source": "P113", "version": "v1",
             "valid_from": null, "valid_to": null, "superseded_by": null}],
  "retired_edges": [],
  "changes": []
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `meta.idempotent_hash` | str | 实体 id 集合 + 边集合的 sha1 前 16 位；**两次运行必须相同**，否则 G2 不通过 |
| `entities[].type_qids` | list[str] | 该实体的全部 P31（多类型实体 177 个） |
| `entities[].lang_source` | str | 标签语言来源（`zh-hans` / `zh-cn` / `zh` / `zh-hant` / `zh-tw`） |
| `edges[].r` / `edges[].source` | str | **属性号**（P113/P121/…），不是中文关系名 |
| `edges[].version` | str | 该边生效的版本 |
| `edges[].valid_from` / `valid_to` | str \| null | 年份；本阶段除 RESTRICT 的退休边（`valid_to="2024"`）外全为 null |
| `edges[].superseded_by` | str \| null | 取代它的边 id（当前全为 null） |
| `edges[].id` | str | **v2 才有**：三元组 sha1 前 12 位，形如 `e:310af5d2f6fd`，跨版本对齐用 |
| `edges[].why` | str | **v2 才有**：这条边为什么存在/为什么被删，逐条可审计 |
| `retired_edges` | list | **v2 才有**：被算子退休的边（与 `edges` 同结构，另带 `id`/`why`） |
| `changes` | list | **v2 才有**：`{op, kind, edge_id, triple, why}`，一个算子一条记录 |

**关键**：`graph_v1.json` 冻结。它是 baseline，也是 500 行标签的输入；改一个字节，全部标签与指标重算。

---

## 文件 2：`data/qa_v1.jsonl` — 题目 + 应然标签

```json
{"qid": "Q001", "branch": "refine", "shape": "count",
 "question": "图里一共有多少国际机场？", "template": "count_class",
 "query": {"op": "count_class", "class": "Q644371"},
 "gold_v1": {"type": "int", "value": 53},
 "gold_v2": {"type": "int", "value": 53},
 "should": "stable", "v1_graph": "graph_v1.json", "v2_graph": "graph_v2_refine.json"}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `qid` | str | 题号；**同一 qid 在 5 个分支里各出现一次**（配对以 `branch + qid + version` 为键） |
| `branch` | enum | `refine` / `restrict` / `merge` / `split` / `all` |
| `shape` | enum | `count` / `set` / `bool` / `hop2`（32 / 24 / 16 / 28 题） |
| `query` | dict | 确定性查询的机器表示；solver 与独立重算都读它，不读自然语言 |
| `gold_v1` / `gold_v2` | dict | `{type, value}`；`type` ∈ `int` / `set` / `bool` / `unanswerable` |
| `should` | enum | `stable` / `flip` / `unanswerable`，由两张图的求解结果**推导**，不是人工标注 |

**关键**：`should = stable` 当且仅当 `gold_v1 == gold_v2`。改这一条规则等于改实验设计。

---

## 文件 3：`baselines/out/live/<method>_<branch>_<version>.jsonl` — 预测

```json
{"qid": "Q001", "method": "bfs2", "version": "v2", "branch": "refine",
 "answer": "20", "evidence": ["e:eb7cdfb1cf48", "..."], "raw": "20",
 "meta": {"temperature": 0, "mode": "live", "model": "deepseek-flash", "seed": 42,
          "graph": "graph_v2_refine.json", "template": "b2-bfs2-v1"}}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `method` | str | `b1_text` / `bfs2` |
| `version` | str | `v1` / `v2`（**merge 分支的 v1 是 `graph_v1_mb.json`**） |
| `branch` | str | 与 qa 配对用；**缺它会导致跨分支重复计数**（曾出过一次报告层误报）。该字段已在实现中使用，**尚未经 A 确认（D16）**，确认前不要当接口约定对外引用 |
| `answer` | str | 空串表示未作答（指标里「拒答抖动」就是靠它识别） |
| `evidence` | list[str] | 用到的边 id；B1 恒为空（它不读图） |
| `meta.mode` | str | `stub` / `live`；**`stub` 的数字不得引用** |
| `meta.model` / `seed` / `temperature` | — | 缺任一，事后无法证明这行是怎么跑出来的 |

**关键**：每行必须自证 `mode / model / version / graph / branch`，由 `scripts/audit_results.py` 逐行检查。

---

## 变更记录

| 日期 | 改了什么 | 谁 | 是否通知全组 |
|---|---|---|---|
| 2026-11-13 | 初版（graph.jsonl / qa.jsonl / pred.jsonl 三文件约定） | — | — |
| 2026-11-17 | 按实际产物重写：图改单文件 JSON、qa 增 `branch/shape/template/query`、pred 增 `branch/meta`；`pred.branch` 尚未经 A 确认（D16） | S | 待 A 确认 |
