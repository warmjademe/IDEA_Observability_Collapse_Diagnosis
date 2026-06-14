#!/usr/bin/env python3
"""Probe whether ark's DeepSeek models actually emit OpenAI-style tool_calls.
This is the crux of why the tool-calling CLI agents (cline/goose/pi/qwen/opencode)
reach the model + reason correctly but never land an edit: if the model returns
plain text instead of a structured tool_call, those agents have nothing to apply."""
import json, sys
import urllib.request

UP = "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
KEY = "YOUR_ARK_API_KEY"
TOOLS = [{"type": "function", "function": {
    "name": "write_file", "description": "Create or overwrite a file with content.",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"]}}}]
MSGS = [{"role": "user", "content": "Create a file named foo.txt containing the text hello. "
                                    "You MUST call the write_file tool to do it."}]


def probe(model):
    body = json.dumps({"model": model, "messages": MSGS, "tools": TOOLS,
                       "tool_choice": "auto", "max_tokens": 512}).encode()
    req = urllib.request.Request(UP, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + KEY,
                                          "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=120)
        d = json.loads(r.read())
        msg = (d.get("choices") or [{}])[0].get("message", {})
        tc = msg.get("tool_calls")
        print(f"\n### {model}")
        print("  HTTP:", r.status)
        print("  finish_reason:", (d.get("choices") or [{}])[0].get("finish_reason"))
        if tc:
            print("  TOOL_CALLS: YES ->", len(tc), "call(s)")
            for c in tc[:2]:
                fn = c.get("function", {})
                print("    fn=", fn.get("name"), "args=", str(fn.get("arguments"))[:120])
        else:
            print("  TOOL_CALLS: NONE  (model returned text instead)")
            print("  content head:", str(msg.get("content"))[:200])
    except Exception as e:
        body = getattr(e, "read", lambda: b"")()
        print(f"\n### {model}\n  ERROR:", str(e)[:120], body[:200])


for m in ["deepseek-v4-flash", "deepseek-v4-pro"]:
    probe(m)
