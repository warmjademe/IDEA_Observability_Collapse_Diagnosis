#!/usr/bin/env python3
"""
ctx_compress_proxy.py — the harness-agnostic context-compression operator, realized
at the model boundary (the formalized kappa_theta: h_t -> u_t).

A reverse proxy on the OpenAI /v1/chat/completions surface. Before forwarding to the
upstream (火山 ark DeepSeek), it applies a controllable, recency-biased context
operator: keep the system message(s) + the FIRST user message (the task = keep_first)
+ the last `--keep` non-system messages, dropping the middle. This evicts the
runtime-discovered mid-conversation context (where late-binding anchors live) while
preserving the task prompt -- exactly the lossy state->observation map of the paper.
`--keep 0` is identity (NoOp / passthrough). Because EVERY harness talks to the model
through this proxy, the same operator (and the same strength knob) applies uniformly
to all harnesses, so the compression knob is flippable for all of them, not just the
one harness with a native condenser.

Run one instance per strength (port == strength):
  python ctx_compress_proxy.py --port 4210 --keep 0     # NoOp / passthrough (control)
  python ctx_compress_proxy.py --port 4211 --keep 12    # mild
  python ctx_compress_proxy.py --port 4212 --keep 6     # moderate
  python ctx_compress_proxy.py --port 4213 --keep 3     # aggressive
"""
import argparse
import os
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

UPSTREAM = "https://ark.cn-beijing.volces.com/api/coding/v3"   # 火山 ark OpenAI surface
ARK_KEYS = ["YOUR_ARK_API_KEY",
            "YOUR_ARK_API_KEY_2"]   # rotate to spread API load
MODEL = "deepseek-v4-flash"
_kc = [0]


def next_key():                                # round-robin (single async worker -> no lock needed)
    k = ARK_KEYS[_kc[0] % len(ARK_KEYS)]
    _kc[0] += 1
    return k


def truncate(messages, keep):
    """keep system + first user (task) + last `keep` non-system messages; drop middle.
    Repairs an orphan leading tool-result (whose tool_call was dropped) to keep the
    request API-valid."""
    if keep <= 0 or not messages:
        return messages, 0
    sysm = [m for m in messages if m.get("role") == "system"]
    non = [m for m in messages if m.get("role") != "system"]
    if len(non) <= keep + 1:
        return messages, 0
    head = non[:1]                                   # the task (keep_first = 1)
    tail = non[-keep:]
    while tail and tail[0].get("role") == "tool":    # drop orphan tool result
        tail = tail[1:]
    # also: an assistant msg carrying tool_calls whose tool replies were dropped would
    # orphan; since tail is a suffix, any assistant-with-tool_calls in tail keeps its
    # following tool replies (they are later in the list, hence also in tail).
    new = sysm + head + tail
    return new, len(non) - len(head) - len(tail)


def build(keep):
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        msgs = body.get("messages", [])
        body["messages"], dropped = truncate(msgs, keep)
        body["model"] = MODEL                        # pin model; ignore provider prefix
        headers = {"Authorization": f"Bearer {next_key()}", "Content-Type": "application/json"}
        if body.get("stream"):                       # SSE passthrough for streaming clients
            async def _sse():
                async with httpx.AsyncClient(timeout=600.0, trust_env=False) as cli:
                    async with cli.stream("POST", UPSTREAM + "/chat/completions", json=body, headers=headers) as r:
                        async for chunk in r.aiter_raw():
                            yield chunk
            return StreamingResponse(_sse(), media_type="text/event-stream",
                                     headers={"x-ctx-dropped": str(dropped), "x-ctx-keep": str(keep)})
        try:
            async with httpx.AsyncClient(timeout=300.0, trust_env=False) as cli:
                r = await cli.post(UPSTREAM + "/chat/completions", json=body, headers=headers)
            return Response(content=r.content, status_code=r.status_code,
                            media_type="application/json",
                            headers={"x-ctx-dropped": str(dropped), "x-ctx-keep": str(keep)})
        except Exception as e:
            return Response(content=('{"error":"proxy: %s"}' % str(e)[:200]).encode(),
                            status_code=502, media_type="application/json")

    @app.get("/health")
    async def health():
        return {"ok": True, "keep": keep, "upstream": UPSTREAM}

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--keep", type=int, required=True)
    a = ap.parse_args()
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    uvicorn.run(build(a.keep), host="127.0.0.1", port=a.port, log_level="warning")
