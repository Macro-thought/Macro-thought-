# T1.1 图增强包（v1.1 / v1.1-600 / v1.2-full / v1.3-1500）

日期：2026-11-17
基础图：`Macro-thought/data/graph_v1.json`（590 实体 / 1857 边，指纹 `d5935c6c56f97176`）
本包**不修改原图**；提供四版增强图、补数缓存、生成/校验脚本、两份报告。

---

## 0. 先选版本（最重要）

| 你的目标 | 用哪个 | 实体 / 边 | domain / schema |
|---|---|---|---|
| 严格守 T1.1 的 400–600 实体 | **`data/graph_v1_1_600.json`** | **600 / 1951** | **1095 / 856** |
| domain 补到 ≥1500 | **`data/graph_v1_3_domain1500.json`** | **718 / 2363** | **1500 / 863** |
| 二跳最全（对照用） | **`data/graph_v1_2_enriched.json`** | **655 / 2017** | **1154 / 863** |
| 中间版（别名多、二跳中） | `data/graph_v1_1.json` | 610 / 1972 | 1109 / 863 |
| 原图 / 已有 500 行标签 | `Macro-thought/data/graph_v1.json` | 590 / 1857 | 994 / 863 |

**一句话：domain 1500 与实体 600 在 6 国种子上不可兼得。**
- 要 600 实体 → 用 `graph_v1_1_600.json`，但 domain 只有 1095；
- 要 domain 1500 → 用 `graph_v1_3_domain1500.json`，但实体 718，T1.1 的 400–600 不满足；
- 两者都要 → 需要扩种子（新增约 80 家航司并删噪声），是一轮新取数，不在本包内。

---

## 1. 这次做了什么

| # | 任务 | 完成 | 证据 |
|---|---|---|---|
| 1 | T1.1 边数拆成 domain / schema | ✅ | meta 写死 `n_domain_edges / n_schema_edges / n_p31 / n_p279` |
| 2 | 补二跳 P176 / P931 | ✅ | v1.1 67+48；v1.2 88+72；v1.3 67+48 |
| 3 | 补 aliases / 旧名 | ✅ | 515/610 实体、2652 条（84.4%）；strict 508/600 |
| 4 | 类型/节点单列 | ✅ | 134 未知 → 118 类 + 13 国家 + 3 未分类；新增 `node_kind` |
| 追加 1 | **domain 补到 ≥1500** | ✅ | v1.3 **1500**（+391 条 P17/P495/P131） |
| 追加 2 | **修 4 条繁简** | ✅ | 四版增强图全部 **0 繁体残留** |

4 条修复：

| 原文 | 修复后 |
|---|---|
| 仁川國際機場 | 仁川国际机场 |
| 內飞地 | 内飞地 |
| 大園区 | 大园区 |
| 赤鱲角 | 赤腊角 |

> `赤鱲角` 用 OpenCC 会转成生僻字「赤𫚭角」，故手工映射为大陆常见写法「赤腊角」。

---

## 2. 四版关键数字

| 项 | v1.1 | v1.1-600 | v1.2-full | v1.3-1500 |
|---|---|---|---|---|
| 实体总数 | 610 | **600** | 655 | **718** |
| 实例（instance） | 477 | 467 | 522 | 578 |
| 类 / 国家 | 118 / 15 | 118 / 15 | 118 / 15 | 118 / 22 |
| 边总数 | 1972 | **1951** | 2017 | **2363** |
| 领域边 | 1109 | **1095** | 1154 | **1500** |
| schema 边（P31+P279） | 863 | 856 | 863 | 863 |
| P176（机型→制造商） | 67 | 66 | **88** | 67 |
| P931（机场→城市） | 48 | 48 | **72** | 48 |
| aliases 实体 / 条数 | 515 / 2652 | 508 / 2627 | 515 / 2652 | 515 / 2652 |
| 繁体残留 | 0 | 0 | 0 | 0 |
| 纯拉丁标签 | 13 | 13 | 13 | 13 |
| 孤儿 / 悬空 / 自环 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| 指纹 | `2c87c27717e42518` | `08db01652c6886c3` | `7fcf0ab19cb7dc8b` | `b6eb1f9ed0820d2f` |

---

## 3. T1.1 验收

| 项 | 要求 | v1.1 | v1.1-600 | v1.2 | v1.3 |
|---|---|---|---|---|---|
| 总边数 | 1500–2500 | 1972 ✅ | 1951 ✅ | 2017 ✅ | 2363 ✅ |
| 领域边 | 1500–2500 | 1109 ❌ | 1095 ❌ | 1154 ❌ | **1500 ✅** |
| 实体总数 | 400–600 | 610 ❌ | **600 ✅** | 655 ❌ | 718 ❌ |
| 实例数 | 400–600（若按实例） | 477 ✅ | 467 ✅ | 522 ✅ | 578 ✅ |
| 中文名 | 100% | 597+13 | 597+13 | 597+13 | 705+13 |
| 繁简 | 统一 | **0** ✅ | **0** ✅ | **0** ✅ | **0** ✅ |
| 孤儿/悬空/自环 | 0 | 0 ✅ | 0 ✅ | 0 ✅ | 0 ✅ |
| source/version | 全部 | ✅ | ✅ | ✅ | ✅ |

**结论**：

- `graph_v1_1_600.json` 是 **T1.1 400–600 的提交版**；domain 1095 仍低于 1500。
- `graph_v1_3_domain1500.json` 是 **domain 1500 的版本**；实体 718，T1.1 的 400–600 不满足。
- 两个目标目前不能在同一张 6 国图上同时满足；本包把选择权交给使用方。

---

## 4. 目录结构

```
t1_1_v1_1_bundle/
├── README.md                 本文件
├── MANIFEST.json             文件清单 + 各版 stats + sha256
├── CHECKSUMS.txt             所有文件的 sha256
├── data/
│   ├── graph_v1_1.json
│   ├── graph_v1_1_600.json
│   ├── graph_v1_2_enriched.json
│   ├── graph_v1_3_domain1500.json
│   ├── v1_1_stats.json
│   ├── v1_1_600_stats.json
│   ├── v1_2_stats.json
│   └── v1_3_stats.json
├── cache/                    QLever 补数缓存（断点续跑用）
│   ├── v1_1_fetch.json
│   ├── v1_1_domain_fetch.json
│   └── v1_1_domain_fetch2.json
├── reports/
│   ├── V1_1_REPORT.md        五版完整对照与取舍
│   └── COMPARE_group_graph.md 与原图的独立对比评价
└── scripts/
    ├── verify_variants.py    校验四版（本包唯一必需脚本）
    ├── make_manifest.py      重新生成 MANIFEST/CHECKSUMS
    ├── fetch_v1_1_missing.py 补 P176/P931/别名
    ├── fetch_domain.py       补 P17/P495/P131
    ├── fetch_domain2.py      补新行政区的 P17/P131
    ├── build_v1_1.py         生成 v1.1
    ├── merge_v1_1_fetch.py   合并别名/已有尾边
    ├── build_v1_1_600.py     生成 strict 600
    ├── build_v1_2.py         生成 full v1.2
    ├── build_v1_3_domain1500.py 生成 v1.3
    ├── patch_v1_3.py         修 v1.3 悬空边
    └── fix_labels_all.py     四版繁简统一
```

---

## 5. 怎么验证

```bash
python scripts/verify_variants.py
```

预期输出：四版的实体/边/domain/P176/P931/alias/繁体/孤儿/悬空/自环 + 指纹；结构不变量失败时退出码 1。
`opencc` 可选：装了会全量查繁体，没装只查 4 条已知标签。

重新生成清单：

```bash
python scripts/make_manifest.py
```

---

## 6. 怎么复现

> **产物已包含；复现是可选的。** 脚本是生成时使用的原始脚本，里面的路径常量指向作者工作区 `D:\repro\schema_change\data`。迁到别的机器/仓库时，若要在本 bundle 内重跑，把脚本里的 `D:\repro\schema_change\data` 改为本 bundle 的 `data/` / `cache/`。

顺序：

```bash
python -u scripts/fetch_v1_1_missing.py   # QLever：P176/P931/别名；有缓存
python -u scripts/fetch_domain.py          # QLever：P17/P495/P131
python -u scripts/fetch_domain2.py         # QLever：新行政区的 P17/P131
python scripts/build_v1_1.py               # v1.1 610
python scripts/merge_v1_1_fetch.py         # 合并别名/已有尾边
python scripts/build_v1_1_600.py           # strict 600
python scripts/build_v1_2.py               # full 655
python scripts/build_v1_3_domain1500.py    # domain 1500
python scripts/patch_v1_3.py               # 修悬空边
python scripts/fix_labels_all.py           # 繁简统一
```

说明：

- QLever（`qlever.dev/api/wikidata`）有 429 限流；`fetch_*.py` 已带磁盘缓存、固定间隔、退避重试，**中途被杀重跑会从缓存接上**。
- `fix_labels_all.py` 需要 `opencc`；其余脚本只用标准库。
- `build_v1_2.py` / `build_v1_3_domain1500.py` 需要 `opencc`（新实体标签 t2s）。
- 产物已包含，正常使用只需要 `verify_variants.py`。

---

## 7. 已知限制

1. **domain 1500 与实体 600 不可兼得**：v1.3 718 实体；v1.1-600 1095 domain。要两者兼得需扩种子。
2. **v1.3 新增 108 个行政区节点**（省/都道府县/市辖区），是 domain 1500 的主要代价；`node_kind` 已把它们标为 instance，`country` 从 15 涨到 22。
3. **13 个纯拉丁标签**（ARJ21、ATR 42、ATR、C919、ANA Wings…）作为品牌/型号例外保留；未登记进 `meta`。
4. **95 个实体没有 altLabel**：不是漏查，是 Wikidata 没有；要旧名需查 P1448/P1813。
5. **5 条二跳边因新尾实体无中文名被跳过**；v1.2 还差 6 个机型、1 个机场。
6. **边级时间仍为 0**：`valid_from/valid_to` 全 null；RESTRICT_REL 只能用属性收窄，不能用时间。
7. **MERGE 仍是合成**：v1 里没有真实同指对；aliases 只能做候选筛查。
8. **P17/P495/P131 是 T1.1 白名单外的补充关系**：P17 在白名单内；P495/P131 是为补 domain 与地点层级新增的，论文里要写明。
9. **类型是“按边角色”分类，不是 Wikidata P31**：`node_kind=class/country/instance` 由 P31/P279/P17 边推断。

---

## 8. 指纹与校验

| 版本 | 文件 | 指纹 |
|---|---|---|
| v1.1 | `data/graph_v1_1.json` | `2c87c27717e42518` |
| v1.1-600 | `data/graph_v1_1_600.json` | `08db01652c6886c3` |
| v1.2-full | `data/graph_v1_2_enriched.json` | `7fcf0ab19cb7dc8b` |
| v1.3-1500 | `data/graph_v1_3_domain1500.json` | `b6eb1f9ed0820d2f` |

- 指纹算法：实体 id 集合 + 边三元组集合的 sha1 前 16 位；**不含标签**（所以修繁简不改指纹）。
- 全包 **30 个文件**（28 个被清单文件 + `MANIFEST.json` + `CHECKSUMS.txt`），约 **2.77 MB**；逐文件 sha256 见 `CHECKSUMS.txt`，结构化清单见 `MANIFEST.json`。

---

## 9. 并入组仓库的建议

1. **不要覆盖** `data/graph_v1.json`；它是 500 行标签/2000 行预测的基线。
2. 把本文件夹放到 `deliverables/t1_1_v1_1/` 或直接放仓库根；`data/*.json` 可以拷进 `data/`，但保留文件名。
3. **T1.1 表用 `graph_v1_1_600.json`**；**domain 1500 实验用 `graph_v1_3_domain1500.json`**；**二跳对照用 `graph_v1_2_enriched.json`**。
4. 若正式替换主图：重算指纹、重跑 500 行标签、重跑基线；**不要只换图不重算标签**。
5. 在 `decisions.md` 记三条：domain 1500 vs 600 的取舍；P17/P495/P131 的补充；4 条繁简修复与 `赤腊角` 专名映射。
6. 在 `docs/numbers.md` / `data_card.md` 补上新文件名、实体/边/domain 数、指纹。

---

## 10. 来源与许可

- 基础图：组员 `Macro-thought/data/graph_v1.json`；Wikidata，经 `qlever.dev`，CC0 1.0。
- P176/P931/aliases：`graph_v1_r2.json` 按 QID 对齐 + QLever 补取（2026-11-17）。
- 4 条繁简：OpenCC t2s + 手工 `赤鱲角→赤腊角`。
- 本包未调用 LLM，无 API 费用；QLever 查询有缓存。
