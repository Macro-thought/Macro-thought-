#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实 LLM 参数兼容性探针
========================
在花钱跑 800 次基线之前，用最少的请求回答四个问题：

    S1  端点活着吗？key 有权限吗？模型名存在吗？
    S2  最小 chat 请求能不能拿到非空 content？
    S3  temperature=0 / seed=42 / reasoning_effort=high 这三个字段会不会被拒？
    S4  reasoning_effort 如果真的被接受，**它生效了吗**？

为什么必须单独写这一份，而不是复用 baselines/llm.py：
    llm._live_answer() 在 HTTPError 时把响应体丢掉了（只抛 "HTTP Error 400"），
    而这里最需要的恰恰是 body —— "model not found" 和 "unknown field reasoning_effort"
    都在 body 里，看不到就只能瞎猜。

三条红线（不是建议，是常量）：
    1. temperature 从 0 改成 0.7 不是"降级"，是改实验条件。服务端不接受 0 时，唯一合法
       出路是「省略字段 + 标注默认值未知」，并且必须由人重新授权。
    2. reasoning_effort 从 high 改成 medium 同理。
    3. 不主动加 max_tokens —— 那是给输出设上限，可能截断列表题答案。

用法：
    python scripts/probe_llm.py              # 跑 S0–S4
    python scripts/probe_llm.py --step s1    # 只跑到某一步
产出：
    data/llm_probe_YYYY-MM-DD.json
    reports/llm_probe_YYYY-MM-DD.md
"""

import argparse
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "baselines" / ".env"
OUT_JSON = ROOT / "data" / f"llm_probe_{date.today().isoformat()}.json"
OUT_MD = ROOT / "reports" / f"llm_probe_{date.today().isoformat()}.md"

# 用户指定的目标参数（改这里等于改实验，需书面授权）
WANT_MODEL = os.environ.get("SCHEMA_CHANGE_LLM_MODEL") or "deepseek-flash"
WANT_TEMPERATURE = 0
WANT_SEED = 42
WANT_EFFORT = os.environ.get("SCHEMA_CHANGE_REASONING_EFFORT", "high")

RECORDS = []


# ---------------------------------------------------------------- 环境

def load_env_file():
    """把 baselines/.env 里的键读进环境变量（不覆盖已有的）。"""
    if not ENV_FILE.exists():
        return False
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)
    return True


def cfg():
    return {
        "key": os.environ.get("OPENAI_API_KEY", ""),
        "base": (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
        "model": WANT_MODEL,
    }


def host_of(url):
    return urllib.parse.urlparse(url).netloc or "(invalid)"


def mask(key):
    if not key:
        return "(空)"
    return f"{key[:6]}…{key[-4:]}（len={len(key)}，sha1={hashlib.sha1(key.encode()).hexdigest()[:8]}）"


# ---------------------------------------------------------------- HTTP

def request(method, path, payload=None, timeout=120):
    """发一次请求，**永远返回 body**，不把 4xx 当异常吞掉。"""
    c = cfg()
    url = c["base"] + path
    headers = {"Content-Type": "application/json"}
    if c["key"]:
        headers["Authorization"] = f"Bearer {c['key']}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 绕开本机死代理
    t0 = time.time()
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        status = exc.code
    except Exception as exc:                                      # noqa: BLE001
        body = f"<{type(exc).__name__}: {exc}>"
        status = -1
    ms = int((time.time() - t0) * 1000)
    rec = {
        "step": "",
        "method": method,
        "path": path,
        "payload": payload,
        "status": status,
        "ms": ms,
        "body_head": body[:2000],
    }
    RECORDS.append(rec)
    return status, body, ms, rec


def jbody(body):
    try:
        return json.loads(body)
    except Exception:                                             # noqa: BLE001
        return None


def chat(payload, step):
    """发一条 /chat/completions，返回 (ok, 解析后的 json, 记录)。"""
    status, body, ms, rec = request("POST", "/chat/completions", payload)
    rec["step"] = step
    js = jbody(body)
    ok = status == 200 and bool(js) and bool(
        (js.get("choices") or [{}])[0].get("message", {}).get("content")
        or (js.get("choices") or [{}])[0].get("message", {}).get("reasoning_content")
    )
    return ok, js, rec


def err_text(body):
    js = jbody(body)
    if js and isinstance(js.get("error"), dict):
        e = js["error"]
        return f"{e.get('type', '')}/{e.get('code', '')}: {e.get('message', '')}".strip(": ")
    return (body or "")[:300]


# ---------------------------------------------------------------- 各步

def s0():
    c = cfg()
    print(f"==> S0 环境")
    print(f"    base  : {c['base']}  (host={host_of(c['base'])})")
    print(f"    model : {c['model']}（请求值）")
    print(f"    key   : {mask(c['key'])}")
    if not c["key"]:
        print("    !! 没有 key。写 baselines/.env 或 export OPENAI_API_KEY")
        return False
    if not c["base"].startswith("http"):
        print("    !! base 不合法")
        return False
    return True


def s1():
    print(f"==> S1 GET /models")
    status, body, ms, rec = request("GET", "/models")
    rec["step"] = "s1"
    js = jbody(body)
    ids = []
    if isinstance(js, dict):
        ids = [m.get("id") for m in (js.get("data") or []) if isinstance(m, dict)]
    print(f"    HTTP {status}  {ms}ms  返回 {len(ids)} 个模型")
    if status in (401, 403):
        print(f"    !! 鉴权失败：{err_text(body)}")
        return False, []
    if status != 200:
        print(f"    ?? /models 不可用（{err_text(body)[:120]}）——不是致命，继续用 S2 判定")
        return True, []
    want = cfg()["model"]
    hit = want in ids
    print(f"    {'✔' if hit else '✘'} 精确命中 {want}：{hit}")
    if not hit and ids:
        near = [i for i in ids if any(t in (i or "").lower() for t in
                                      (want.split("-")[0].lower(), "deepseek", "flash", "chat"))]
        print(f"    近似候选：{near[:12] or ids[:12]}")
    return True, ids


def s2():
    c = cfg()
    print(f"==> S2 最小 chat（不带任何采样参数）")
    ok, js, rec = chat({"model": c["model"],
                        "messages": [{"role": "user", "content": "ping"}]}, "s2")
    if ok:
        msg = js["choices"][0]["message"]
        print(f"    ✔ HTTP 200，content={msg.get('content')!r}，model={js.get('model')}")
        return True, js
    print(f"    ✘ HTTP {rec['status']}：{err_text(rec['body_head'])}")
    return False, None


def s3(base_payload):
    """逐步加参数，返回 (级别, 生效 payload, 降级记录)。"""
    level, payload, degraded = "L0", dict(base_payload), []
    print(f"==> S3a 加 temperature={WANT_TEMPERATURE} / seed={WANT_SEED}")
    p = dict(payload, temperature=WANT_TEMPERATURE, seed=WANT_SEED)
    ok, js, rec = chat(p, "s3a")
    if ok:
        print("    ✔ 被接受")
        payload = p
    else:
        msg = err_text(rec["body_head"])
        print(f"    ✘ {rec['status']}：{msg}")
        if "seed" in msg.lower():
            payload = dict(payload, temperature=WANT_TEMPERATURE)
            degraded.append({"field": "seed", "why": msg, "http": rec["status"]})
            level = "L2"
            ok2, _, rec2 = chat(payload, "s3a_retry")
            print(f"    去掉 seed 重试：{'✔ 通过' if ok2 else '✘ ' + err_text(rec2['body_head'])}")
            if not ok2:
                return "L3", payload, degraded
        else:
            degraded.append({"field": "temperature/seed", "why": msg, "http": rec["status"]})
            return "L3", dict(payload), degraded

    print(f"==> S3b 加 reasoning_effort={WANT_EFFORT}")
    p = dict(payload, reasoning_effort=WANT_EFFORT)
    ok, js, rec = chat(p, "s3b")
    if ok:
        print("    ✔ 被接受（注意：被接受 ≠ 生效，S4 验证）")
        payload = p
    else:
        msg = err_text(rec["body_head"])
        print(f"    ✘ {rec['status']}：{msg}")
        degraded.append({"field": "reasoning_effort", "why": msg, "http": rec["status"]})
        level = "L1"
    return level, payload, degraded


def s4(payload_with_effort):
    """验证 reasoning_effort 是否真的生效：三条证据任一成立即可。"""
    print(f"==> S4 验证 reasoning_effort 是否生效（同一 prompt 各一次）")
    q = "用一句话说明：为什么温度参数会让同一问题得到不同答案？"
    with_effort = dict(payload_with_effort)
    without = {k: v for k, v in payload_with_effort.items() if k != "reasoning_effort"}

    ok_a, js_a, rec_a = chat(dict(with_effort, messages=[{"role": "user", "content": q}]), "s4_high")
    time.sleep(1)
    ok_b, js_b, rec_b = chat(dict(without, messages=[{"role": "user", "content": q}]), "s4_plain")

    def usage(js):
        return ((js or {}).get("usage") or {})

    ua, ub = usage(js_a), usage(js_b)
    reasoning_tokens = (((ua.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0)
    has_rc = bool(((js_a or {}).get("choices") or [{}])[0].get("message", {}).get("reasoning_content"))
    ca, cb = ua.get("completion_tokens") or 0, ub.get("completion_tokens") or 0
    ratio = (ca / cb) if cb else None

    ev = {"reasoning_tokens": reasoning_tokens, "has_reasoning_content": has_rc,
          "completion_high": ca, "completion_plain": cb,
          "ratio": round(ratio, 2) if ratio else None,
          "usage_high": ua, "usage_plain": ub,
          "fingerprint": (js_a or {}).get("system_fingerprint")}
    honored = bool(reasoning_tokens > 0 or has_rc or (ratio and ratio >= 2))
    print(f"    reasoning_tokens={reasoning_tokens}  reasoning_content={has_rc}  "
          f"completion {ca} vs {cb}（ratio={ev['ratio']}）")
    print(f"    结论：{'✔ 生效' if honored else '✘ 未观察到生效（键被接受但被忽略）'}")
    return honored, ev


# ---------------------------------------------------------------- 汇总

def verdict(level, honored, models):
    """把结果压成一个可执行结论。"""
    if level == "L3":
        return ("STOP", "服务端不接受 temperature=0。禁止改成 0.7（那是改实验），须人工决定。")
    if level == "L4" or not models:
        return ("STOP", "模型名不可用。按约定不自动换名，须人工确认候选。")
    if level == "L1":
        return ("NEED-OK", "reasoning_effort 被拒，已去掉。若你坚持要 high，需换端点。")
    if level == "L1p":
        return ("GO-WITH-CAVEAT", "参数全部被接受，但 reasoning_effort 未观察到生效；报告不得写“high 生效”。")
    if level == "L0" and not honored:
        return ("GO-WITH-CAVEAT", "同上：键被接受但无生效证据。")
    return ("GO", "参数全接受且 reasoning_effort 有生效证据。")


def write_reports(level, payload, degraded, honored, ev, ids, ok_all):
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    def redact(rec):
        r = dict(rec)
        if r.get("payload"):
            r["payload"] = {k: v for k, v in r["payload"].items() if k != "messages"}
        return r

    doc = {
        "date": date.today().isoformat(),
        "base_host": host_of(cfg()["base"]),
        "model_requested": cfg()["model"],
        "model_listed": ids,
        "params_requested": {"temperature": WANT_TEMPERATURE, "seed": WANT_SEED,
                             "reasoning_effort": WANT_EFFORT},
        "params_effective": {k: v for k, v in payload.items() if k != "messages"},
        "level": level,
        "reasoning_effort_honored": honored,
        "evidence": ev,
        "degraded": degraded,
        "ok_all": ok_all,
        "records": [redact(r) for r in RECORDS],
    }
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# LLM 参数探针回执（{date.today().isoformat()}）", "",
         f"- 端点：`{cfg()['base']}`（host=`{host_of(cfg()['base'])}`）",
         f"- 模型（请求）：`{cfg()['model']}`",
         f"- key：`{mask(cfg()['key'])}`（不落盘全文）", "",
         "## 一、逐步结果", "",
         "| 步 | 请求 | HTTP | 耗时 | body 摘要 |", "|---|---|---|---|---|"]
    for r in RECORDS:
        L.append(f"| {r['step'] or '-'} | {r['method']} {r['path']} | {r['status']} | "
                 f"{r['ms']}ms | `{(r['body_head'] or '')[:100].replace('|','\\|').replace(chr(10),' ')}` |")

    L += ["", "## 二、参数最终生效情况", "",
          f"- 级别：**{level}**",
          f"- 请求参数：`{json.dumps({k: v for k, v in doc['params_requested'].items()}, ensure_ascii=False)}`",
          f"- 生效参数：`{json.dumps({k: v for k, v in doc['params_effective'].items()}, ensure_ascii=False)}`",
          f"- reasoning_effort 生效证据：`{json.dumps(ev, ensure_ascii=False)}`"]
    if degraded:
        L += ["", "### 降级记录", ""]
        for d in degraded:
            L.append(f"- 去掉 `{d['field']}`：HTTP {d['http']}，`{d['why'][:160]}`")

    v, why = verdict(level if level != "L0" or honored else "L1p", honored, ids)
    L += ["", "## 三、结论", "", f"**{v}** —— {why}", "",
          "## 四、下一步", "",
          "1. 若为 GO / GO-WITH-CAVEAT：进入 S1 代码加固。",
          "2. 若为 NEED-OK / STOP：停下来找人，不自动改参数、不自动换模型。",
          "", "> 本文件由 `scripts/probe_llm.py` 生成，密钥不写入。"]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\n→ {OUT_JSON.relative_to(ROOT)}\n→ {OUT_MD.relative_to(ROOT)}")
    return v


def main():
    ap = argparse.ArgumentParser(description="DeepSeek/OpenAI 兼容端点参数探针")
    ap.add_argument("--step", default="all", choices=["all", "s1", "s2", "s3", "s4"])
    args = ap.parse_args()

    load_env_file()
    if not s0():
        return 2
    if args.step == "s1":
        s1()
        return 0

    ok1, ids = s1()
    if not ok1:
        write_reports("L5", {}, [], False, {}, [], False)
        return 3

    ok2, js2 = s2()
    if not ok2:
        write_reports("L4", {}, [], False, {}, ids, False)
        print("\n!! 最小 chat 失败：模型名或权限问题。按约定停下，不自动换名。")
        return 4

    level, payload, degraded = s3({"model": cfg()["model"],
                                   "messages": [{"role": "user", "content": "ping"}]})
    if level in ("L3",):
        write_reports(level, payload, degraded, False, {}, ids, False)
        return 5

    honored, ev = s4(payload) if "reasoning_effort" in payload else (False, {})
    v = write_reports(level, payload, degraded, honored, ev, ids, True)

    print("\n" + "=" * 60)
    print(f"最终判定：{v}（level={level}, honored={honored}）")
    print("=" * 60)
    return 0 if v in ("GO", "GO-WITH-CAVEAT") else 6


if __name__ == "__main__":
    sys.exit(main())
