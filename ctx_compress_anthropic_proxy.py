#!/usr/bin/env python3
"""
ctx_compress_anthropic_proxy.py — the SAME context-compression operator as
ctx_compress_proxy.py, but on the Anthropic /v1/messages surface, for harnesses
that speak Anthropic (OpenHands, Claude Code). Keep system + first user (task) +
last `--keep` messages; repair anthropic tool-pairing (window must start with a
user message; drop orphan tool_result blocks whose tool_use was truncated away);
strip DeepSeek's null-signature thinking blocks from both request and response
(else the harness's embedded client / the upstream rejects them). Forward to 火山
ark's native Anthropic surface. `--keep 0` = NoOp passthrough (still strips
thinking). One instance per strength (port == strength):
  ... --port 4220 --keep 0   (NoOp control)
  ... --port 4221 --keep 12
  ... --port 4222 --keep 6
  ... --port 4223 --keep 3
"""
import argparse
import os
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

UPSTREAM = "https://ark.cn-beijing.volces.com/api/coding"   # 火山 native Anthropic surface
ARK_KEYS = ["YOUR_ARK_API_KEY",
            "YOUR_ARK_API_KEY_2"]   # rotate to spread API load
MODEL = "deepseek-v4-flash"
_THINK = {"thinking", "redacted_thinking"}
_kc = [0]


def next_key():
    k = ARK_KEYS[_kc[0] % len(ARK_KEYS)]
    _kc[0] += 1
    return k


def _strip_blocks(content):
    if isinstance(content, list):
        return [b for b in content if not (isinstance(b, dict) and b.get("type") in _THINK)]
    return content


def truncate(messages, keep):
    if keep <= 0 or len(messages) <= keep + 1:
        out = messages
        dropped = 0
    else:
        head = messages[:1]                       # first user message = the task
        tail = list(messages[-keep:])
        while tail and tail[0].get("role") != "user":   # window must start with user
            tail = tail[1:]
        if tail and isinstance(tail[0].get("content"), list):  # drop orphan tool_result
            m0 = dict(tail[0])
            m0["content"] = [b for b in m0["content"]
                             if not (isinstance(b, dict) and b.get("type") == "tool_result")]
            tail[0] = m0
            if not m0["content"]:
                tail = tail[1:]
                while tail and tail[0].get("role") != "user":
                    tail = tail[1:]
        out = head + tail
        dropped = len(messages) - len(out)
    # strip thinking blocks from assistant messages in the (kept) request
    cleaned = []
    for m in out:
        if m.get("role") == "assistant":
            m = dict(m); m["content"] = _strip_blocks(m.get("content"))
        cleaned.append(m)
    return cleaned, dropped


def build(keep):
    app = FastAPI()

    @app.post("/v1/messages")
    async def messages(req: Request):
        body = await req.json()
        body["messages"], dropped = truncate(body.get("messages", []), keep)
        body["model"] = MODEL
        _k = next_key()
        headers = {"x-api-key": _k, "Authorization": f"Bearer {_k}",
                   "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        # Streaming clients (Claude Code CLI) request stream=true and expect an SSE
        # event-stream back; pass those bytes through untouched (r.json() would choke
        # on SSE -> the 502 "Expecting value" we saw). Request-side truncation + the
        # assistant thinking-strip already happened above, so the operator still bites;
        # response-side thinking-strip is unnecessary because we re-strip on resend.
        if body.get("stream"):
            async def _sse():
                async with httpx.AsyncClient(timeout=600.0, trust_env=False) as cli:
                    async with cli.stream("POST", UPSTREAM + "/v1/messages", json=body, headers=headers) as r:
                        async for chunk in r.aiter_raw():
                            yield chunk
            return StreamingResponse(_sse(), media_type="text/event-stream",
                                     headers={"x-ctx-dropped": str(dropped), "x-ctx-keep": str(keep)})
        try:
            async with httpx.AsyncClient(timeout=300.0, trust_env=False) as cli:
                r = await cli.post(UPSTREAM + "/v1/messages", json=body, headers=headers)
            data = r.json()
            if isinstance(data.get("content"), list):           # strip thinking from response
                data["content"] = _strip_blocks(data["content"])
            import json as _j
            return Response(content=_j.dumps(data).encode(), status_code=r.status_code,
                            media_type="application/json",
                            headers={"x-ctx-dropped": str(dropped), "x-ctx-keep": str(keep)})
        except Exception as e:
            return Response(content=('{"type":"error","error":{"message":"proxy: %s"}}' % str(e)[:160]).encode(),
                            status_code=502, media_type="application/json")

    @app.get("/health")
    async def health():
        return {"ok": True, "keep": keep, "surface": "anthropic", "upstream": UPSTREAM}

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--keep", type=int, required=True)
    a = ap.parse_args()
    os.environ["NO_PROXY"] = "*"; os.environ["no_proxy"] = "*"
    uvicorn.run(build(a.keep), host="127.0.0.1", port=a.port, log_level="warning")
