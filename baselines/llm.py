#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 LLM 接口：stub / 真实调用 / 磁盘缓存
=========================================
三条纪律，写在代码里而不是文档里
  1. **temperature 只能是 0**。不是"调参调出来的 0"，而是实验设计前提：
     旧答案是否翻转，必须是 schema 变化引起的，不能是采样引起的。
     所以 `ask()` 收到非 0 直接抛错，而不是"按你说的调一下"。
  2. **seed 固定**。真实 API 的 seed 只是"尽力而为"，真要复现靠的是下面的缓存 +
     stub；seed 写进签名是为了让输出记录有据可查。
  3. **默认不联网**。`stub=True` 是默认值，真实调用要显式 `stub=False` 且环境里有 key；
     没有 key 时抛错而不是静默回落 stub —— 静默回落会让"跑了 76 行结果"看起来像真的，
     这是最坏的一种实验事故。

缓存：key = sha1(prompt + model + mode + temperature + seed)，落 `baselines/.cache/`。
mode 进 key 是必须的：否则 stub 的结果会污染真实调用的缓存（反之亦然）。
磁盘缓存不只是省钱，它让"同一 prompt 一定得到同一答案"成为可验证的性质。

输出契约（顺便放在这一层，基线只负责检索）
  - `answer_form(shape)`：shape → 中文答案形式
  - `parse_answer(raw, shape)`：模型自由文本 → 与 gold 可比对的规范串
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TEMPERATURE = 0          # 冻结。见模块头 1.
SEED = 42                # 冻结
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
DEFAULT_MODEL = "gpt-4o-mini"          # 仅作 OpenAI 兼容端点的占位名，可用环境变量覆盖
# 超时：reasoning 模型 + 近千字符中文 prompt，60s 偏紧，允许环境变量放宽（工程参数，不影响答案分布）
TIMEOUT = int(os.environ.get("SCHEMA_CHANGE_LLM_TIMEOUT", "60"))
# 推理档位：None=不发该字段。只有非 None 才进 body。
REASONING_EFFORT = os.environ.get("SCHEMA_CHANGE_REASONING_EFFORT") or None
# 重试：只重试"再试一次可能就好了"的状态；4xx 语义错误重试无意义
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4

ENV_KEY = "OPENAI_API_KEY"
ENV_BASE = "OPENAI_BASE_URL"
ENV_MODEL = "SCHEMA_CHANGE_LLM_MODEL"

def _load_dotenv():
    """把 baselines/.env 读进环境变量（不覆盖已有值）。

    放在模块导入时执行：这样 `python baselines/b2_bfs.py --live` 单独跑也能拿到 key，
    不必先手动 export。文件已在 .gitignore 里，不会入库。
    """
    p = Path(__file__).resolve().parent / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

SHAPE_FORM = {"count": "整数", "hop2": "整数", "set": "列表", "bool": "是否"}


class LLMError(RuntimeError):
    """带诊断上下文的错误。kind/status/attempts 会写进输出行的 meta.error。"""

    def __init__(self, msg, kind=None, status=None, attempts=None):
        super().__init__(msg)
        self.kind = kind
        self.status = status
        self.attempts = attempts


def answer_form(shape: str) -> str:
    return SHAPE_FORM.get(shape, "整数")


def mode_name(stub: bool) -> str:
    """输出行里必须落这个字段：没有它，事后无法区分哪些数字是真跑出来的。"""
    return "stub" if stub else "live"


def model_name(model: str | None = None) -> str:
    """真实模式下实际用的模型名；stub 模式返回 'stub'，避免把占位结果误读成某模型的成绩。"""
    if model is None and not os.environ.get(ENV_KEY):
        return "stub"
    return model or os.environ.get(ENV_MODEL) or DEFAULT_MODEL


# ---------------------------------------------------------------- 输出规范化

_REFUSE = ("不知道", "无法确定", "无法回答", "不确定", "信息不足", "证据不足")


def parse_answer(raw: str, shape: str) -> str:
    """模型输出 → 规范答案串。答不出返回空串（字段冻结要求）。

    - 整数：取第一个整数。B1/B2 都是"数出来"的，模型常带解释，取首个数字够用。
    - 是否：统一成小写 true/false，便于和 gold 的 JSON bool 对齐。
    - 列表：按顿号/逗号切分、去重、**按标签排序** —— 集合语义，顺序不该影响判等；
      下游比较也应按集合比（gold 侧是按实体 id 排序的标签，顺序天然不同）。
    """
    text = (raw or "").strip()
    if not text or any(t in text for t in _REFUSE):
        return ""
    if shape in ("count", "hop2"):
        m = re.search(r"-?\d+", text)
        return m.group(0) if m else ""
    if shape == "bool":
        low = text.lower()
        if text.startswith("是") or low.startswith(("true", "yes")):
            return "true"
        if text.startswith(("否", "不是")) or low.startswith(("false", "no")):
            return "false"
        return ""
    if shape == "set":
        parts = [p.strip(" 。.；;") for p in re.split(r"[、,，;；|\n]", text)]
        out = {p for p in parts if p and p not in _REFUSE}
        return "、".join(sorted(out))
    return text


# ---------------------------------------------------------------- 缓存

def _cache_key(prompt: str, model: str, mode: str, temperature, seed,
               reasoning_effort=None, base_host="") -> str:
    """缓存键。effort 与端点必须进 key：否则降级重跑会静默命中上一档缓存，
    "参数改了但结果没变"会看起来像"参数不影响答案"，是最隐蔽的一类污染。"""
    h = hashlib.sha1()
    h.update(prompt.encode("utf-8"))
    for x in (model, mode, str(temperature), str(seed),
              str(reasoning_effort or ""), base_host):
        h.update(b"\x00")
        h.update(x.encode("utf-8"))
    return h.hexdigest()


def _cache_path(cache_dir, key: str) -> Path:
    d = Path(cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _cache_read(cache_dir, key, model, mode):
    p = _cache_path(cache_dir, key)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # 坏缓存当未命中，重算即可（不让缓存污染结果）
    if rec.get("model") != model or rec.get("mode") != mode:
        return None
    return rec.get("response")


def _cache_write(cache_dir, key, rec: dict) -> None:
    # 原子写：先写 .part 再 os.replace。并发时另一个进程可能正好读到写了一半的
    # 文件，_cache_read 会把坏 JSON 当未命中，于是同一 prompt 被重复调用一次
    # （2026-11-17 全量跑：b1 的 v1/v2 并发抢同一 prompt，B1 负控因此出现 6 条翻转）。
    p = _cache_path(cache_dir, key)
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


class _KeyLock:
    """同一缓存键的互斥锁（跨进程）。

    为什么需要：20 个 cell 在 4–6 个进程里并发跑，B1 的 v1/v2 读同一张冻结语料，
    prompt 完全相同。没有锁时两边会同时"读不到缓存 → 各调一次 API"，拿回两个不同
    的答案（seed 不保证服务端逐字复现），一个写进缓存、另一个留在自己的输出里。
    后果不是"多花了钱"，而是负控基线 v1≠v2，整张 FR 表的地基被抽掉。
    """

    def __init__(self, cache_dir, key: str, stale_after: float = 900.0):
        # 锁文件是 <key>.lock，**不能**用 _cache_path（它硬加 .json）：
        # 否则锁会以 <key>.lock.json 落在缓存目录里，被成本统计 / 缓存扫描当成坏缓存。
        self.path = _cache_path(cache_dir, key).with_suffix(".lock")
        self.key = key
        self.stale_after = stale_after

    def __enter__(self):
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except (FileExistsError, PermissionError):
                # PermissionError 也当真锁：Windows 上另一个进程正在删除/打开同一文件时
                # os.open(O_EXCL) 会抛它，而不是 FileExistsError。
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue                      # 对方刚释放，立刻重试
                if age > self.stale_after:        # 进程被杀留下的孤儿锁
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass
        return False


# ---------------------------------------------------------------- stub

_RE_Q = re.compile(r"问句\s*[：:]\s*(.+)")
_RE_FORM = re.compile(r"答案形式\s*[：:]\s*(\S+)")
_RE_LINE = re.compile(r"^\s*\d+\s*[.、]\s*(.+)$", re.M)
_RE_EID = re.compile(r"\s*\[e:[0-9a-f]+\]\s*$")


def _stub_evidence(prompt: str):
    """从 prompt 里抠出 (头, 关系, 尾)。只认 `1. 头 ｜ 关系 ｜ 尾 [e:...]` 这种行。

    用全角竖线做分隔符是因为中文标签里几乎不可能出现它，正则不会切错。
    """
    out = []
    for m in _RE_LINE.finditer(prompt):
        s = _RE_EID.sub("", m.group(1).strip())
        parts = [p.strip() for p in s.split("｜")]
        if len(parts) == 3 and all(parts):
            out.append(tuple(parts))
    return out


def _stub_answer(prompt: str) -> str:
    """确定性假模型：一个"只会按字面归并"的读者。

    它不懂关系语义、不做否定推理、不做任何图操作，只做三件事：
      1. 从问句里找"在证据中出现过的最长标签"当锚点（纯字符串包含）；
      2. 整数题 → 数含锚点的证据行；列表题 → 取含锚点行的尾标签去重排序；
      3. 是否题 → 弃权（返回空串）。

    为什么是非题弃权：全称判断需要"否定证据"（某个实例没有 R），而 B1/B2 的上下文
    都是正向事实的截断，扁平文本上做全称判断必然靠猜。stub 在这里返回 true/false 会
    人为抬高"稳定率"——宁可留空，让"答不出"这个真实失败模式出现在表里。

    注意：它**不**读 gold、不读图，只读 prompt。所以两条基线喂什么它答什么，
    这正是我们要验证的"管道是否连通"，而不是"方法是否有效"。
    """
    mq, mf = _RE_Q.search(prompt), _RE_FORM.search(prompt)
    if not mq or not mf:
        return ""                       # prompt 不符合约定 → 弃权，而不是瞎猜
    qtext, form = mq.group(1).strip(), mf.group(1).strip()
    evid = _stub_evidence(prompt)
    if not evid:
        return ""

    labels = {x for e in evid for x in (e[0], e[2]) if x}
    # 排序后再取最长：避免依赖 set 迭代顺序（跨进程 PYTHONHASHSEED 不同会影响 str 哈希）
    cands = sorted((l for l in labels if l in qtext), key=lambda s: (-len(s), s))
    anchor = cands[0] if cands else None
    sub = [e for e in evid if anchor in (e[0], e[2])] if anchor else evid

    if form == "整数":
        return str(len(sub))
    if form == "列表":
        tails = sorted({e[2] for e in sub if e[2] != anchor})
        return "、".join(tails)
    return ""                            # 是否 → 弃权


# ---------------------------------------------------------------- 真实调用

def _live_answer(prompt: str, model: str, temperature, seed,
                 reasoning_effort=None) -> dict:
    """真实调用。返回 {text, usage, latency_ms, attempts, http_status, model}。

    三条设计取舍：
    1. **4xx 不重试、5xx/429/超时要重试**。语义错误重试一万次还是错，只会把一次明确失败
       变成一次漫长失败；而 429 和超时是"再试一次可能就好了"。
    2. **错误一定带响应体**。只抛 `HTTP Error 400` 等于把最有用的诊断信息丢掉——
       `model not found` 和 `unknown field reasoning_effort` 都只出现在 body 里。
    3. **429 尊重 Retry-After**，但封顶 60s，避免服务端给一个离谱值把整轮挂住。
    """
    key = os.environ.get(ENV_KEY, "").strip()
    if not key:
        raise LLMError(
            f"未设置 {ENV_KEY}：真实调用被显式拒绝。"
            "本项目默认 stub，若确实要联网请先 export key；不会静默回落到 stub。")
    base = os.environ.get(ENV_BASE, "https://api.openai.com/v1").rstrip("/")
    body = {
        "model": model,
        "temperature": temperature,
        "seed": seed,
        "messages": [{"role": "user", "content": prompt}],
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort          # 只有显式给了才发

    req = urllib.request.Request(
        f"{base}/chat/completions", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST")
    # 本机 http(s)_proxy 指向一个连不通的代理（README 环境坑 1），显式绕过，
    # 否则表现为"DNS 正常但全部超时"，排查起来极像 key 失效。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    last_err = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.time()
        try:
            with opener.open(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
            latency = int((time.time() - t0) * 1000)
            data = json.loads(raw)
            msg = data["choices"][0]["message"]
            text = msg.get("content") or ""
            return {"text": text, "usage": data.get("usage") or {},
                    "latency_ms": latency, "attempts": attempt,
                    "http_status": status,
                    "model": data.get("model") or model,
                    "has_reasoning_content": bool(msg.get("reasoning_content")),
                    "system_fingerprint": data.get("system_fingerprint")}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            status = exc.code
            last_err = f"HTTP {status}: {raw[:500]}"
            if status not in RETRY_STATUS:
                raise LLMError(f"LLM 请求被拒（不可重试）：{last_err}",
                               kind="http", status=status, attempts=attempt) from exc
            ra = exc.headers.get("Retry-After") if exc.headers else None
            wait = min(float(ra), 60.0) if (ra or "").replace(".", "").isdigit() \
                else 0.8 * (2 ** (attempt - 1)) + random.uniform(0, 0.4)
            if attempt < MAX_ATTEMPTS:
                time.sleep(wait)
        except Exception as exc:                              # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(0.8 * (2 ** (attempt - 1)) + random.uniform(0, 0.4))
    raise LLMError(f"LLM 连续 {MAX_ATTEMPTS} 次失败：{last_err}",
                   kind="retries_exhausted", attempts=MAX_ATTEMPTS)


# ---------------------------------------------------------------- 对外

def ask(prompt: str, *, stub: bool = True, model: str = None,
        temperature=TEMPERATURE, seed=SEED, cache_dir=None,
        reasoning_effort=None) -> str:
    """统一入口。默认 stub；缓存命中直接返回，不产生任何网络流量。

    reasoning_effort 默认取环境变量 SCHEMA_CHANGE_REASONING_EFFORT（未设则不发送该字段）。
    """
    if temperature != TEMPERATURE:
        raise LLMError(f"temperature 必须为 {TEMPERATURE}（冻结值），收到 {temperature}。"
                       "本项目测的是 schema 变化导致的翻转，不允许混入采样噪声。")
    if seed != SEED:
        raise LLMError(f"seed 必须为 {SEED}（冻结值），收到 {seed}。")
    model = model or os.environ.get(ENV_MODEL, DEFAULT_MODEL)
    effort = reasoning_effort if reasoning_effort is not None else REASONING_EFFORT
    mode = "stub" if stub else "live"
    cdir = Path(cache_dir) if cache_dir else CACHE_DIR
    base_host = urllib.parse.urlparse(
        os.environ.get(ENV_BASE, "https://api.openai.com/v1")).netloc

    key = _cache_key(prompt, model, mode, temperature, seed, effort, base_host)
    hit = _cache_read(cdir, key, model, mode)
    if hit is not None:
        return hit

    # 未命中 → 先抢这个 key 的锁，拿到锁后再读一次缓存：抢锁期间可能已有别的
    # 进程把同一个 prompt 跑完并写盘，那就直接用它的结果，不再重复调用。
    with _KeyLock(cdir, key):
        hit = _cache_read(cdir, key, model, mode)
        if hit is not None:
            return hit

        rec = {"prompt_sha1": key, "mode": mode, "model": model,
               "temperature": temperature, "seed": seed,
               "reasoning_effort": effort, "base_host": base_host,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if stub:
            text = _stub_answer(prompt)
        else:
            out = _live_answer(prompt, model, temperature, seed, effort)
            text = out["text"]
            rec.update({k: out[k] for k in
                        ("usage", "latency_ms", "attempts", "http_status",
                         "has_reasoning_content", "system_fingerprint")})
            rec["model_effective"] = out["model"]
        rec["response"] = text
        _cache_write(cdir, key, rec)
        return text


def safe_ask(prompt: str, **kw):
    """ask() 的不抛版本：返回 (text, error)。

    为什么需要它：1000 次调用里，至少一次 429 / 超时是常态。若让单题异常上抛，
    整轮会 traceback 且不留任何产物——一次偶发失败毁掉一小时的工作。
    失败写在 meta.error 里，指标侧把它当"未作答"处理，语义上是诚实的。
    """
    try:
        return ask(prompt, **kw), None
    except LLMError as exc:
        return "", {"kind": getattr(exc, "kind", None) or "llm_error",
                    "status": getattr(exc, "status", None),
                    "attempts": getattr(exc, "attempts", None),
                    "message": str(exc)[:300]}
