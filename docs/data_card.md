# 数据卡：航空子图 v1（graph_v1.json）

| 项 | 内容 |
|---|---|
| 名称 | 行业图谱 schema 变更研究 · 航空子图 v1 |
| 文件 | `data/graph_v1.json` |
| 版本 | v1（2026-11-16 构建） |
| 源 | Wikidata，经 `https://qlever.dev/api/wikidata` 取数 |
| 上游许可 | Wikidata 数据以 CC0 1.0 释出；本子图沿用 CC0 |
| 规模 | 590 实体 / 1857 边 / 平均度 6.3 |
| 确定性指纹 | `d5935c6c56f97176`（实体集合 + 边集合的 sha1 前 16 位） |
| 构建脚本 | `scripts/fetch_subgraph.py`（13 条 SPARQL，全部缓存可重放） |
| 校验脚本 | `scripts/verify_subgraph.py` |

---

## 一、怎么建的

1. **种子**：`?e wdt:P31/wdt:P279* wd:Q46970`（航空公司）且 `wdt:P17` ∈ {中国 Q148, 香港 Q8646, 澳门 Q14773, 台湾地区 Q865, 日本 Q17, 韩国 Q884} → 216 家。
2. **一跳扩展**：六条白名单关系 `P121 P113 P176 P749 P127 P159` 的出边。
3. **补边**：所有实体的 `P31`（类型）与 `P17`（国家），以及 P31 类之间的 `P279` 层级。加这三类边的原因不是凑规模——P31 与 P279 是 T1.3 的 REFINE_TYPE 算子的必要输入。
4. **修剪**：丢弃无中文标签的实体（71 个，含 32 家种子航司）→ 迭代删除度数为 0 的孤儿（1 个）。
5. **繁简统一**：标签按 `zh-hans → zh-cn → zh → zh-hant → zh-tw` 回退；回退到 `zh/zh-hant/zh-tw` 的 182 条再经 zhconv 转简体，实际改动 65 条。
6. **把 P31/P17 的目标节点也纳入实体集**（类节点、国家节点），否则类型边会悬空。这批节点只取标签、不取类型，故 131 个节点显示"未标注"。

## 二、字段

```
entities[] : id, label_zh, label_en, lang_source, type, type_qids[], country, aliases[], is_seed
edges[]    : h, r, t, source, version, valid_from, valid_to, superseded_by
meta       : version, built_at, endpoint, seeds_requested, seed_class, seed_countries,
             whitelist_props, fanout, n_entities, n_edges, zh_dropped, orphan_dropped,
             simplify, idempotent_hash
```

- `r` 与 `source` 存**属性号**（P121/P113/…），不存中文关系名；中文映射留给 T2.1 的语料模板。
- `version` 恒为 `v1`；`valid_from` / `valid_to` / `superseded_by` 本阶段全部为 null，由 T1.3 的算子负责填写——**这是与 `docs/SCHEMA.md` 保持兼容的字段，不要删。**
- `type` 是主类型的中文标签（取第一个存在于实体集的 P31 类）；正式类型树由 T1.2 产出。

## 三、已知偏差（写论文时必须交代）

1. **没有航线网络。** 机场关系只有 `P113`（枢纽，177 条，覆盖 129/184 家航司）。`P121` 是"运营的机型/设施"而**不是**"运营于机场"，实测尾节点为波音 747、A380 等机型。凡"某机场有哪些航司执飞"的题，**本图不可答**。
2. **制造商是二跳。** `P176` 从航司出发为 0 条；正确路径是 航司 `P121` → 机型 `P176` → 制造商。T1.1 未取二跳。
3. **外围噪声节点。** `P159`（总部所在地）与 `P749/P127` 会带入行政区、办公楼、个人。实测含 1 个人物（方威）、6 个"区"、5 个"日本的市"、若干"办公大楼"。结构上合法，业务上无关，出题应回避。
4. **131 个节点无类型。** 类节点与国家节点只取了标签，`type` 显示"未标注"。
5. **中文名 100% 是以丢弃换来的。** 216 家种子航司里 32 家因无中文标签被删（85.2%），一跳邻居删 16 个（95.1%）。若后续需要这些实体，须放宽语言策略并重算覆盖率。
6. **繁简转换有残留。** 182 条可疑中有 117 条经 zhconv 转换后与原文一致（多为简体用字或专名），未逐条人工核验。

## 四、能用来做什么 / 不能用来做什么

**可以**：多跳问答（枢纽机场、母公司、总部、机型）、计数题（多少家航司运营某机型）、全称题（是否所有货运航空都运营货机）、schema 变更实验（REFINE/RESTRICT/MERGE/SPLIT 四类算子的输入）。

**不要**：航线网络分析（数据不存在）、把 `type` 当权威类型体系（T1.2 才是）、把 `P121` 读成机场关系、拿它做时效性实验（本图的时间限定词未取，`valid_from/valid_to` 全为 null）。

## 五、复现

```bash
cd <仓库根目录>
python scripts/fetch_subgraph.py     # 有缓存 0.1 秒；首次约 12 分钟
python scripts/verify_subgraph.py    # 结构 + 幂等 + 语义抽检 + 人工复核清单
```

取数期间遭遇 qlever.dev 的 nginx 限流（HTTP 429，实测约每小时只放 6–8 条查询）。脚本已做磁盘缓存与退避重试，**中途被杀后重跑会从缓存接上**，不会重复消耗配额。
若需换源：`--endpoint https://wikidata.demo.openlinksw.com/sparql`（该镜像种子数 210，与 216 略有差异；换源后 `meta.endpoint` 会留痕，本数据卡需同步更新）。
