#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B1 朴素 RAG —— 噪声底噪 / negative control
==========================================
**B1 不读图。** 它把三元组线性化成一段扁平文本（corpus），做词法检索，取 top-k 段落
塞进 prompt，让 LLM 直接生成答案。没有邻域扩展、没有类型闭包、没有关系语义、没有
任何"从 A 跳到 B"的推理。它代表"把知识图谱当文档库用"的下限做法。

**为什么它是负控（全表的解释基准）**
  B1 的语料是**一次冻结、与版本无关**的文本（默认取自 graph_v1.json，见
  `DEFAULT_CORPUS_GRAPH`）。也就是说，同一个问题在 v1 与 v2 上喂给 LLM 的证据、
  提示、参数完全相同 → 输出必须完全相同。配合 temperature=0 + 固定 seed + 磁盘缓存，
  B1 的翻转率按构造恒等于 **0**，它不是"测出来的 0"，而是"设计出来的 0"。

  这个 0 有两个用处：
    (a) 它把"运行噪声"这一项锁死。任何方法报出的翻转，都不能再用"采样抖动"解释；
    (b) 它是全表的**解释基准**：如果某个方法在 B1 上观察到非 0 翻转，那说明实现
        不确定（缓存没命中、排序不稳、拼 prompt 时混入了版本信息），是 bug 不是发现。
  审稿人最该盯的就是这里：B1 的 evidence 在 v2 行里可能引用 v2 已退休的边——那是
  "语料不随 schema 变"的直接后果，不是错，也正好说明 B1 根本感知不到 schema 变化。

**三个冻结项**（写进签名默认值并落进输出记录）
  temperature=0（llm.TEMPERATURE）、seed=42（llm.SEED）、prompt 模板（本文件唯一一份，
  改模板必须改 `TEMPLATE_ID`，否则新旧结果会被当成同一组实验混在一起）。

**检索为什么用字符 bigram 的 BM25**
  中文没有离线分词器可用，而任务禁止引入需要联网下载的模型。字符 bigram 是无监督、
  零依赖、对中文实体名（"中国南方航空"）召回稳定的折中；代价是会把"航空"这类高频
  词根打得很重，检索结果偏"字面相似"而非"语义相关"——这恰是朴素 RAG 的真实样子。

用法：
    python baselines/b1_text.py --graph data/graph_v1.json --out baselines/out/b1_v1.jsonl
    python baselines/b1_text.py --graph data/graph_v1.json --live      # 显式联网
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import math
import re
from pathlib import Path

import graph_access as ga
import llm

METHOD = "b1_text"
TEMPLATE_ID = "b1-rag-v1"
TOP_K = 20          # 与 B2 的 20 条边上限对齐：两者拿到相近的上下文预算，差异才归因于"检索是否有损"

# 语料一律从这里冻结。**刻意不跟随 --graph**：B1 的全部意义就是"语料不随版本变"。
DEFAULT_CORPUS_GRAPH = Path(__file__).resolve().parent.parent / "data" / "graph_v1.json"

PROMPT_TEMPLATE = """你是严谨的航空知识图谱问答助手。你只能依据下面给出的证据作答，不得使用证据之外的知识。

问句：{question}

证据（按检索分数从高到低排列，共 {n} 条）：
{evidence}

答案形式：{form}
输出要求：只输出答案本身，不要解释。
"""


# ---------------------------------------------------------------- 语料（一次冻结）

def _linearize(hl: str, rl: str, tl: str) -> str:
    """三元组 → 一句中文。检索用自然语序，和 evidence 行格式刻意不同（见下）。"""
    return f"{hl}的{rl}是{tl}"


def build_corpus(path=DEFAULT_CORPUS_GRAPH, cache_dir=None):
    """把图当"文档库"摊平成 [(id, text)]，结果按文件内容 hash 缓存。

    这里用裸 json.load 而不是 Graph：B1 不需要任何图结构（不建索引、不走邻域），
    连"图访问层"都不该碰——否则"B1 不读图"这句话就成了空话。
    """
    p = Path(path)
    raw = p.read_bytes()
    # 格式号进缓存 key：以后改 docs 结构时不会静默读到旧缓存（缺字段会变成"答案莫名变空"）
    key = hashlib.sha1(raw + b"|corpus-fmt1").hexdigest()[:12]
    cdir = Path(cache_dir) if cache_dir else llm.CACHE_DIR
    cache = cdir / f"corpus_{p.stem}_{key}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # 坏缓存重算

    d = json.loads(raw.decode("utf-8"))
    ent = {e["id"]: e for e in d.get("entities", [])}
    seen, docs = set(), []
    for e in sorted(d.get("edges", []), key=lambda x: (x["h"], x["r"], x["t"])):
        eid = e.get("id") or ga.edge_id(e["h"], e["r"], e["t"])
        if eid in seen:
            continue
        seen.add(eid)
        hl = ent.get(e["h"], {}).get("label_zh") or e["h"]
        tl = ent.get(e["t"], {}).get("label_zh") or e["t"]
        rl = ga.r_label(e["r"])
        docs.append({"id": eid, "h": hl, "r": rl, "t": tl, "text": _linearize(hl, rl, tl)})
    docs.sort(key=lambda x: x["id"])

    cdir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return docs


# ---------------------------------------------------------------- 检索

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+")


def _tokens(s: str):
    out = []
    for seg in _TOKEN_RE.findall(s.lower()):
        if seg.isascii():
            out.append(seg)
        elif len(seg) == 1:
            out.append(seg)
        else:
            out.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return out


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf, self.dl, df = [], [], {}
        for d in docs:
            cnt = {}
            for t in _tokens(d["text"]):
                cnt[t] = cnt.get(t, 0) + 1
            self.tf.append(cnt)
            self.dl.append(sum(cnt.values()))
            for t in cnt:
                df[t] = df.get(t, 0) + 1
        n = len(docs)
        self.n = n
        self.avgdl = (sum(self.dl) / n) if n else 0.0
        self.idf = {t: math.log(1 + (n - m + 0.5) / (m + 0.5)) for t, m in df.items()}

    def search(self, query, k):
        qt = _tokens(query)
        scored = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in qt:
                f = self.tf[i].get(t)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.dl[i] / self.avgdl)
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            if s > 0:
                scored.append((s, d))
        # 打平按 id：没有这个 tie-break，浮点相等的两条文档顺序会随入参漂移
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        picked = [d for _, d in scored[:k]]
        if len(picked) < k:
            # 不足 k 时按 id 顺序补齐：上下文预算固定为 k 条，否则"上下文长度"会随
            # 查询漂移，成为未受控变量（B1 与 B2 的边数上限就不对齐了）。
            got = {d["id"] for d in picked}
            for d in self.docs:
                if len(picked) >= k:
                    break
                if d["id"] not in got:
                    picked.append(d)
        return picked


def _evidence_block(docs) -> str:
    """evidence 行格式：`序号. 头 ｜ 关系 ｜ 尾 [id]`。全角竖线做分隔，正则切不错。"""
    return "\n".join(f"{i}. {d['h']} ｜ {d['r']} ｜ {d['t']} [{d['id']}]"
                     for i, d in enumerate(docs, 1))


# ---------------------------------------------------------------- 主流程

def branch_of(gname: str) -> str:
    """从图文件名推变更分支：graph_v2_split.json -> split；graph_v1.json -> v1。
    写进输出行是为了让「这张表属于哪个算子」不必再靠文件名猜。"""
    stem = Path(gname).stem
    parts = stem.split("_")
    if len(parts) >= 3 and parts[1] == "v2":
        return parts[2]
    return stem.replace("graph_", "")


def run_graph(questions, graph_path, out_path, *, stub=True, top_k=TOP_K,
              cache_dir=None, corpus_graph=None, version=None, branch=None, resume=False):
    """对一张图的每个问题产出一行。注意：`graph_path` 只用于填 version/meta，不参与作答。"""
    cdir = Path(cache_dir) if cache_dir else llm.CACHE_DIR
    gname = Path(graph_path).name
    version = version or ga.read_version(graph_path)   # 只读 meta，不建图；v2 输出可显式覆盖
    branch = branch or branch_of(gname)
    docs = build_corpus(corpus_graph or DEFAULT_CORPUS_GRAPH, cdir)
    index = BM25(docs)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    rows, done = [], set()
    if resume and out.exists():
        for line in out.read_text("utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows.append(r)
                done.add(r["qid"])
        print(f"    resume: 已有 {len(done)} 行，跳过这些题")
    fh = tmp.open("w", encoding="utf-8", newline="\n")
    # 同 b2_bfs：resume 的旧行要先落到 tmp，否则 os.replace 会把它们丢掉。
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    fh.flush()

    for q in questions:
        if q["qid"] in done:
            continue
        question = q.get("nl") or json.dumps(q.get("query", {}), ensure_ascii=False)
        hit = index.search(question, top_k)
        prompt = PROMPT_TEMPLATE.format(
            question=question, n=len(hit),
            evidence=_evidence_block(hit), form=llm.answer_form(q["shape"]))
        raw, err = llm.safe_ask(prompt, stub=stub, cache_dir=cdir)
        row = {
            "qid": q["qid"],
            "method": METHOD,
            "version": version,
            "branch": branch,          # score.py 只认顶层 branch，不认 meta.branch
            "answer": llm.parse_answer(raw, q["shape"]),
            "evidence": [d["id"] for d in hit],
            "raw": raw,
            "meta": {
                "temperature": llm.TEMPERATURE,
                "seed": llm.SEED,
                "graph": gname,                  # 实际读入的图
                "version": version,              # 本行声称对应的版本（可与 graph 不同：B1 是负控）
                "branch": branch,
                "mode": llm.mode_name(stub),     # stub / live，缺此字段则结果不可审计
                "model": llm.model_name(),
                "template": TEMPLATE_ID,
            },
        }
        if err:
            row["meta"]["error"] = err
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        rows.append(row)

    fh.close()
    os.replace(tmp, out)                      # 全部成功才替换，半截文件不会被当成结果
    order = {q["qid"]: i for i, q in enumerate(questions)}
    rows.sort(key=lambda r: order.get(r["qid"], 10 ** 9))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="B1 朴素 RAG（负控）")
    ap.add_argument("--questions", default="data/questions_smoke.json")
    ap.add_argument("--graph", default="data/graph_v1.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--live", action="store_true", help="真实调用（默认 stub，不联网）")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--version", default=None,
                    help="覆盖输出行里的 version（B1 负控：读 v1 图但声称回答 v2，必须分开记）")
    ap.add_argument("--branch", default=None, help="变更分支；不给则由图名推断")
    ap.add_argument("--resume", action="store_true", help="跳过输出文件里已有的 qid")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 题（pilot 用）")
    ap.add_argument("--qids", default=None, help="只跑指定 qid，逗号分隔")
    args = ap.parse_args(argv)

    qs = json.loads(Path(args.questions).read_text("utf-8"))["questions"]
    if args.qids:
        want = {x.strip() for x in args.qids.split(",") if x.strip()}
        qs = [q for q in qs if q["qid"] in want]
    if args.limit:
        qs = qs[:args.limit]
    version = args.version or ga.read_version(args.graph)
    out = args.out or f"baselines/out/{llm.mode_name(not args.live)}/{METHOD}_{args.branch or version}_{version}.jsonl"
    rows = run_graph(qs, args.graph, out, stub=not args.live,
                     top_k=args.top_k, cache_dir=args.cache_dir, version=args.version, branch=args.branch, resume=args.resume)
    n_ans = sum(1 for r in rows if r["answer"])
    print(f"[{METHOD}] mode={'live' if args.live else 'stub'} graph={Path(args.graph).name} "
          f"rows={len(rows)} answered={n_ans} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
