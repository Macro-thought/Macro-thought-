# scripts 说明

这些脚本是生成四版图时使用的**原始脚本**，里面的 `D:\repro\schema_change\data` 是作者工作区路径。
产物已经包含在 `../data/`，正常使用**只需要** `verify_variants.py`；其余脚本用于复现/审计。

- `verify_variants.py`：本包唯一必需的脚本，纯标准库，校验四版结构/指纹/T1.1 定位。
- `make_manifest.py`：重新生成 `MANIFEST.json` 与 `CHECKSUMS.txt`。
- `fetch_*.py`：QLever 补数，带磁盘缓存；限流时会退避重试，断点续跑。
- `build_*.py` / `merge_*.py` / `patch_*.py` / `fix_labels_all.py`：生成/修边/繁简统一。

若要在本 bundle 内重跑：

1. 把脚本里的 `D:\repro\schema_change\data` 改成 `../data`（或本 bundle 的绝对路径）；
2. 把 `CACHE` 路径改成 `../cache/...`；
3. `fix_labels_all.py` / `build_v1_2.py` / `build_v1_3_domain1500.py` 需要 `opencc`，其余只用标准库。

QLever 端点：`https://qlever.dev/api/wikidata`，实测有 429（每小时约 6–8 条查询）。
`fetch_*.py` 已按 120–150 一批、固定间隔、指数退避设计；**不要并发跑**，否则更容易 429。
