# 基线输出清单（as-found，2026-11-17）

这些文件是被 `baselines/.gitignore` 忽略的（`out/` 整目录）。此清单记录它们入库前的状态，
用于事后证明「当时到底跑了什么」。**全部为 stub 模式产出的占位结果，不得引用其数字。**

| 文件 | 行数 | mode | model | 首行 version | 首行 meta.graph | sha256(前16) |
|---|---|---|---|---|---|---|
| `b1_all_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1_mb.json` | `40231526431cdd21` |
| `b1_all_v2.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1_mb.json` | `40231526431cdd21` |
| `b1_merge_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1_mb.json` | `40231526431cdd21` |
| `b1_merge_v2.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1_mb.json` | `40231526431cdd21` |
| `b1_refine_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `54e60b0f821769f0` |
| `b1_refine_v2.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `54e60b0f821769f0` |
| `b1_restrict_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `54e60b0f821769f0` |
| `b1_restrict_v2.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `54e60b0f821769f0` |
| `b1_split_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `54e60b0f821769f0` |
| `b1_split_v2.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `54e60b0f821769f0` |
| `b1_text_v1.jsonl` | 19 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `89b055faedfaa41f` |
| `b1_text_v2.jsonl` | 19 | (缺字段) | (缺字段) | v2 | `graph_v2_split.json` | `4b60e8d423f804ad` |
| `b2_all_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1_mb.json` | `ffa6e95e945fabe7` |
| `b2_all_v2.jsonl` | 100 | (缺字段) | (缺字段) | v2 | `graph_v2_all.json` | `5a342ca8143c504b` |
| `b2_merge_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1_mb.json` | `ffa6e95e945fabe7` |
| `b2_merge_v2.jsonl` | 100 | (缺字段) | (缺字段) | v2 | `graph_v2_merge.json` | `e0403e7139678b35` |
| `b2_refine_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `1d64376b3e930a32` |
| `b2_refine_v2.jsonl` | 100 | (缺字段) | (缺字段) | v2 | `graph_v2_refine.json` | `6f8bd67b39a6b2a0` |
| `b2_restrict_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `1d64376b3e930a32` |
| `b2_restrict_v2.jsonl` | 100 | (缺字段) | (缺字段) | v2 | `graph_v2_restrict.json` | `e74ba78c717591e9` |
| `b2_split_v1.jsonl` | 100 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `1d64376b3e930a32` |
| `b2_split_v2.jsonl` | 100 | (缺字段) | (缺字段) | v2 | `graph_v2_split.json` | `1a74dbafd4d6e216` |
| `bfs2_v1.jsonl` | 19 | (缺字段) | (缺字段) | v1 | `graph_v1.json` | `fd5b92ab712a39f9` |
| `bfs2_v2.jsonl` | 19 | (缺字段) | (缺字段) | v2 | `graph_v2_split.json` | `9bded36f0b8f634f` |

## 结论

- 24 个文件**全部缺 `mode` 字段**，无法从产物本身区分 stub 与真实调用；
- **5 个** v2 文件的 `version` 仍写 `v1`、`meta.graph` 指向 `graph_v1*.json`：`b1_all_v2`、`b1_merge_v2`、`b1_refine_v2`、`b1_restrict_v2`、`b1_split_v2`。这 5 个是 `b1_text.py` 之外的另一条调用路径产出的，没有回填版本参数；
- 同分支的 `b1_*_v1.jsonl` 与 `b1_*_v2.jsonl` **字节完全相同**（如 all 分支两者都是 `40231526431c…`）。B1 不读图、语料固定，所以 v1/v2 答案本应一致——这是它作为「负控」的设计意图。但版本字段写错会让 `metrics/score.py` 按图名解析分支时错配，必须修元数据；
- `baselines/.cache/` 的 443 条应答 `mode` 全为 `stub`。

