# Related work 题名核实（2026-11-17）

> 核实原则：只采用本次实际打开页面上的题名/作者/DOI；仅见 arXiv 者注明预印本，不补全"正式发表"信息。

## 结论速览

| 简称 | 核实状态 | 完整题名 | 年份/发表处 |
|---|---|---|---|
| XGRAG | 部分核实（题名对但出处待定） | XGRAG: A Graph-Native Framework for Explaining KG-based Retrieval-Augmented Generation | 2026 / arXiv:2604.24623（预印本） |
| OKGQA-P | 部分核实（非独立题名） | 实为 OKGQA 论文内的扰动变体；论文题名为 *Can Knowledge Graphs Make Large Language Models More Trustworthy? An Empirical Study Over Open-ended Question Answering* | 2025 / ACL 2025（Long），pp. 12685–12701 |
| ΔSemantics | 已核实 | ΔSemantics: a neuro-symbolic framework for dynamic ontological reasoning with proof-carrying machine learning | 2026 / Knowledge and Information Systems 68, article 283 |
| VersionRAG | 部分核实（题名对但出处待定） | VersionRAG: Version-Aware Retrieval-Augmented Generation for Evolving Documents | 2025 / arXiv:2510.08109（预印本） |
| HoH | 已核实 | HoH: A Dynamic Benchmark for Evaluating the Impact of Outdated Information on Retrieval-Augmented Generation | 2025 / ACL 2025（Long），pp. 6036–6063 |
| PolyGraph | 部分核实（系统名，非题名） | Keep Your Receipts: Trustworthy Cleanup of Agent-Built Knowledge Graphs | 2026 / arXiv:2610.17719；NeurIPS 2026 workshop 预印本 |
| Noy & Klein 2004 | 已核实 | Ontology Evolution: Not the Same as Schema Evolution | 2004 / Knowledge and Information Systems 6(4): 428–440 |
| Kondylakis 2012 | 已核实 | Ontology Evolution: Assisting Query Migration | 2012 / ER 2012，LNCS 7532，pp. 331–344 |

## 逐条

### 1. XGRAG
- 完整题名：XGRAG: A Graph-Native Framework for Explaining KG-based Retrieval-Augmented Generation
- 作者：Zhuoling Li, Ha Linh Hong Tran Nguyen, Valeria Bladinieres, Maxim Romanovsky
- 年份 / 发表处：2026 / arXiv:2604.24623 [cs.AI]，v1 提交于 2026-04-27；未见到正式会议或期刊版本
- DOI / URL：https://doi.org/10.48550/arXiv.2604.24623 ；https://arxiv.org/abs/2604.24623
- 证据：https://arxiv.org/abs/2604.24623 （已打开，题名、四位作者、提交日期、arXiv DOI 均取自该页）
- 与我们的关系：图扰动解释；可对照我们的结构扰动。
- 置信度：中 + 元数据在 arXiv 页面自洽，但仅 v1 预印本，无同行评议与正式出处；作者顺序勿按二手站点转抄。

### 2. OKGQA-P
- 完整题名：**没有以 "OKGQA-P" 为题的论文**。OKGQA-P 是 OKGQA 论文第 3.2 节提出的"语义与结构被故意扰动/污染"的实验变体（benchmark variant）。所属论文题名：Can Knowledge Graphs Make Large Language Models More Trustworthy? An Empirical Study Over Open-ended Question Answering
- 作者：Yuan Sui, Yufei He, Zifeng Ding, Bryan Hooi
- 年份 / 发表处：2025 / ACL 2025（Proceedings of the 63rd Annual Meeting of the ACL, Volume 1: Long Papers），pp. 12685–12701
- DOI / URL：https://doi.org/10.18653/v1/2025.acl-long.622 ；https://aclanthology.org/2025.acl-long.622/
- 证据：https://aclanthology.org/2025.acl-long.622/ （已打开，卷期、页码、DOI 均取自该页）；https://arxiv.org/abs/2410.08085 （已打开，Comments 明确 "accepted by ACL 2025"，摘要写明 OKGQA-P 为 benchmark variant）
- 与我们的关系：边级污染扰动，非 schema 级变更。
- 置信度：高 + ACL Anthology 正式出版页与 arXiv 互证；但"OKGQA-P"只能作为变体名引用，不能当论文题名。

### 3. ΔSemantics
- 完整题名：ΔSemantics: a neuro-symbolic framework for dynamic ontological reasoning with proof-carrying machine learning
- 作者：Rahul Kumar Singh, Ashok Kumar, Rajat Kumar
- 年份 / 发表处：2026 / Knowledge and Information Systems（KAIS），Volume 68，article number 283；Published 14 October 2026（Received 18 Oct 2025，Accepted 11 Sep 2026）
- DOI / URL：https://doi.org/10.1007/s10115-026-02897-w
- 证据：https://link.springer.com/article/10.1007/s10115-026-02897-w （已打开，题名、三位作者、卷 68/文章号 283、四个日期与 DOI 均取自该页）
- 与我们的关系：版本本体上验证并修复，前向对照。
- 置信度：高 + Springer 正式出版页，卷/文章号/日期齐全；注意题名首字符是希腊字母 Δ，不是拉丁字母 "D"。

### 4. VersionRAG
- 完整题名：VersionRAG: Version-Aware Retrieval-Augmented Generation for Evolving Documents
- 作者：Daniel Huwiler, Kurt Stockinger, Jonathan Fürst（Zurich University of Applied Sciences）
- 年份 / 发表处：2025 / arXiv:2510.08109 [cs.IR]，v1 提交于 2025-10-09；检索未见正式会议/期刊版本
- DOI / URL：https://doi.org/10.48550/arXiv.2510.08109 ；https://arxiv.org/abs/2510.08109
- 证据：https://arxiv.org/pdf/2510.08109v1 （已打开，首页题名、三位作者与单位）；https://www.semanticscholar.org/reader/f2be23371f37f73a582bb7dd772a1acb6f8bd3c3 （已打开，记录为 ArXiv 2025, abs/2510.08109）
- 与我们的关系：文档版本感知，不审计 schema 变更。
- 置信度：中高 + 题名与作者一致且可复现，但仅有 arXiv 预印本，正式发表状态未核实。

### 5. HoH
- 完整题名：HoH: A Dynamic Benchmark for Evaluating the Impact of Outdated Information on Retrieval-Augmented Generation
- 作者：Jie Ouyang, Tingyue Pan, Mingyue Cheng, Ruiran Yan, Yucong Luo, Jiaying Lin, Qi Liu
- 年份 / 发表处：2025 / ACL 2025（Long Papers），pp. 6036–6063，Vienna
- DOI / URL：https://doi.org/10.18653/v1/2025.acl-long.301 ；https://aclanthology.org/2025.acl-long.301/
- 证据：https://aclanthology.org/2025.acl-long.301 （已打开，Anthology ID、页码、DOI、七位作者均取自该页）；https://arxiv.org/abs/2503.04800 （已打开，arXiv 版与作者列表一致）
- 与我们的关系：过时信息伤害 RAG，与后向审计同源。
- 置信度：高 + ACL 正式出版页；缩写展开为 "How Outdated information Harms Retrieval-Augmented Generation"，不是 "History of..."。

### 6. PolyGraph
- 完整题名：Keep Your Receipts: Trustworthy Cleanup of Agent-Built Knowledge Graphs（PolyGraph 是文中系统名，不在题名内）
- 作者：Vishisht Choudhary（Technical University of Munich）
- 年份 / 发表处：2026 / arXiv:2610.17719 [cs.AI]，v1 提交于 2026-10-13；Comments 标注为 NeurIPS 2026 workshop "Who Verifies the Agents? Toward Reliable Agent Development"，属 workshop 预印本（camera-ready 可能不同）
- DOI / URL：https://doi.org/10.48550/arXiv.2610.17719 ；https://arxiv.org/abs/2610.17719
- 证据：https://arxiv.org/abs/2610.17719 （已打开，题名、单作者、提交日期、workshop comments 均取自该页）；https://neurips.cc/virtual/2026/172927 （已打开，workshop 页面摘要使用 "We introduce PolyGraph"）
- 与我们的关系：撤回源后清理派生图，属后向维护。
- 置信度：中 + 系统名与"清理被污染图"的描述吻合，但题名不含 PolyGraph，且仅 workshop 预印本；同名/近名文献至少三篇（见下），引用必须用完整题名锁定。

### 7. Noy & Klein 2004
- 完整题名：Ontology Evolution: Not the Same as Schema Evolution
- 作者：Natalya F. Noy, Michel Klein
- 年份 / 发表处：2004 / Knowledge and Information Systems，6(4): 428–440（Published 01 July 2004）
- DOI / URL：https://doi.org/10.1007/s10115-003-0137-2
- 证据：https://link.springer.com/article/10.1007/s10115-003-0137-2 （已打开，题名、作者、卷 6 页 428–440、出版日期均取自该页）；https://research.vu.nl/ws/portalfiles/portal/29675469/KAIS03.pdf （已打开，VU 机构库版本首页标注同一 DOI）
- 与我们的关系：本体演化≠schema 演化的经典论述。
- 置信度：高 + Springer 正式页与机构库 PDF 双证；DOI 尾段是 -0137-2，勿与 ΔSemantics 的 -02897-w 混淆。

### 8. Kondylakis 2012
- 完整题名：Ontology Evolution: Assisting Query Migration
- 作者：Haridimos Kondylakis, Dimitris Plexousakis（FORTH, Greece）
- 年份 / 发表处：2012 / ER 2012（31st International Conference on Conceptual Modeling），LNCS 7532，pp. 331–344；Published 15 October 2012
- DOI / URL：https://doi.org/10.1007/978-3-642-34002-4_26
- 证据：https://link.springer.com/chapter/10.1007/978-3-642-34002-4_26 （已打开，题名、两位作者、LNCS 7532、pp. 331–344 均取自该页）；https://dlnext.acm.org/doi/10.1007/978-3-642-34002-4_26 （已打开，会议名与 2012-10-15 出版日期一致）
- 与我们的关系：本体演化使旧查询失效，需迁移。
- 置信度：高 + Springer 章节页与 ACM 记录互证；但这是"查询迁移"论文，不是 Evolva 系统论文。

## 组内文档的疑似错误

1. **OKGQA-P 被当成一篇论文（最主要错误）**：查无此题名。正确做法是引用 Sui et al., ACL 2025 的 OKGQA 论文，正文写 "OKGQA-P（该文的扰动变体，§3.2）"。若参考文献里单列 "OKGQA-P"，应删除或改为 variant 说明。
2. **HoH 缩写展开错**：组内猜的 "History of..." / hierarchical 均不对。HoH = "How Outdated information Harms Retrieval-Augmented Generation"（题名内的 backronym），正式题名以 "HoH:" 开头。
3. **PolyGraph 被当成题名**：正式题名是 "Keep Your Receipts: Trustworthy Cleanup of Agent-Built Knowledge Graphs"。且该名有歧义：
   - 本次锁定的 KG 清理工作（系统名 PolyGraph，Choudhary，arXiv 2610.17719）；
   - Technion 的 POLYGRAPH：用 KG 遍历探测 LLM 知识缺口（https://ece.technion.ac.il/?p=49822/ ，仅院系页面，正式出处未核实）；
   - USENIX Security 2023 的 POLIGRAPH：隐私政策知识图谱（拼写不同，https://www.usenix.org/system/files/usenixsecurity23-cui.pdf ）。
   引用时必须用完整题名，不能只写 "PolyGraph"。
4. **XGRAG 题名漏副标题**：完整题名含 "A Graph-Native Framework for Explaining KG-based Retrieval-Augmented Generation"；且仅 arXiv v1，不可写成会议/期刊论文。
5. **ΔSemantics 题名与卷期写法**：首字母是希腊 Δ；副标题 "a neuro-symbolic framework for dynamic ontological reasoning with proof-carrying machine learning" 不可省；出处应写 "KAIS 68, article 283 (2026)"，不是页码。
6. **Kondylakis 2012 与 Evolva 混指**：2012 年这篇是 "Ontology Evolution: Assisting Query Migration"（ER 2012）；若组内原意是 Evolva 系统，则不是这篇，需另找 Evolva 原始文献并重新核实（本次未核）。
7. **VersionRAG 出处待定**：目前只有 arXiv:2510.08109，参考文献中应标 arXiv 预印本，不能写 "2026 会议"。
8. **Noy & Klein 的 DOI 尾段易错**：正确为 10.1007/s10115-003-0137-2；不要套用同期刊 2026 年 ΔSemantics 的 DOI 格式。

## 检索记录

| 检索词 | 工具 | 命中情况 |
|---|---|---|
| `XGRAG explainable graph retrieval augmented generation` | WebSearch | 首条即 arXiv:2604.24623，题名完全匹配 |
| `"OKGQA-P" benchmark knowledge graph question answering` | WebSearch | 无独立论文；命中 OKGQA 原文（arXiv:2410.08085），确认 OKGQA-P 为变体 |
| `aclanthology OKGQA "Can Knowledge Graphs Make Large Language Models More Trustworthy" 2025.acl-long` | WebSearch | 命中 2025.acl-long.622，页码/DOI 齐全 |
| `"Delta Semantics" ontology evolution revalidate repair Knowledge and Information Systems` | WebSearch | 命中 Springer 文章页 10.1007/s10115-026-02897-w |
| `VersionRAG version-aware retrieval augmented generation paper` | WebSearch | 命中 arXiv:2510.08109 及 Google Scholar/Semantic Scholar 记录，均标 arXiv |
| `VersionRAG Huwiler Stockinger Fürst accepted conference journal 2026` | WebSearch | 仅 arXiv/CoRR 记录，未发现正式会议或期刊版 |
| `"HoH" knowledge graph question answering multi-hop paper` | WebSearch | 未命中 HoH；一度被 StepChain/HamQA 干扰 |
| `"HoH" acronym paper title ontology OR "knowledge graph" OR "question answering" 2024 2025` | WebSearch | 命中 ACL 2025 HoH（2025.acl-long.301），题名与七位作者齐全 |
| `PolyGraph knowledge graph cleaning poisoned graph paper` | WebSearch | 命中 "Keep Your Receipts"（arXiv:2610.17719），摘要明确系统名 PolyGraph |
| `"PolyGraph" knowledge graph poisoning attack defense cleaning` | WebSearch | 仍以 "Keep Your Receipts" 为主；另见 BAAI 中文解读，未增加新出处 |
| `"PolyGraph" title knowledge graph paper` | WebSearch | 暴露同名歧义：Technion POLYGRAPH、USENIX POLIGRAPH |
| `Noy Klein 2004 "Ontology Evolution: Not the Same as Schema Evolution" DOI` | WebSearch | 命中 VU 机构库 PDF 与 BibSonomy，DOI 10.1007/s10115-003-0137-2 |
| `Kondylakis 2012 ontology evolution mapping evolution Evolva` | WebSearch | 命中 ER 2012 "Ontology Evolution: Assisting Query Migration"，DOI 10.1007/978-3-642-34002-4_26 |

**打开过的原始页面（非二手摘要站）**：arxiv.org/abs/2604.24623、arxiv.org/abs/2410.08085、aclanthology.org/2025.acl-long.622/、link.springer.com/article/10.1007/s10115-026-02897-w、arxiv.org/pdf/2510.08109v1、aclanthology.org/2025.acl-long.301、arxiv.org/abs/2503.04800、arxiv.org/abs/2610.17719、neurips.cc/virtual/2026/172927、link.springer.com/article/10.1007/s10115-003-0137-2、link.springer.com/chapter/10.1007/978-3-642-34002-4_26。
