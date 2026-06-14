#!/usr/bin/env python3
"""Inventory every ICSE sut config: family, agent_name, image, surface hint, base-url env, model.
Groups by harness family so we can pick one config per family to route through the compress proxy."""
import glob, os, yaml, re

SUT = "/home/qyb/TongBu/ICSE_2027_Overeager/Source_Codes/configs/sut"
FAMILIES = ["aider", "claude_code", "claude-code", "cline", "codex", "crush", "goose",
            "open_interpreter", "opencode", "openhands", "pi", "qwen", "swe_agent",
            "mini_swe", "gemini", "zhiyingai"]


def fam(name):
    for f in FAMILIES:
        if name.startswith(f):
            return f
    return name.split("_")[0]


rows = {}
for f in sorted(glob.glob(SUT + "/*.yaml")):
    n = os.path.basename(f)[:-5]
    try:
        c = yaml.safe_load(open(f).read()) or {}
    except Exception as e:
        print("ERR", n, str(e)[:60]); continue
    e = c.get("container_env", {}) or {}
    base = {k: str(v) for k, v in e.items()
            if ("BASE" in k or "URL" in k or "ANTHROPIC" in k.upper()) and "PATH" not in k.upper()}
    bpath = {k: str(v) for k, v in e.items() if "PATH" in k.upper() and "URL" in k.upper()}
    surface = "anthropic" if any("ANTHROPIC" in k.upper() or "messages" in str(v).lower() or "LITELLM" in k.upper()
                                 for k, v in e.items()) else "openai"
    rows.setdefault(fam(n), []).append(dict(
        cfg=n, agent=c.get("agent_name", "?"), img=str(c.get("image", "?")),
        model=str(e.get("OE_MODEL", "-")), surface=surface, base=base, bpath=bpath,
        entry=str(c.get("entrypoint", "") or c.get("cmd", ""))[:50]))

for family in sorted(rows):
    print("\n#### %s  (%d configs)" % (family, len(rows[family])))
    for r in rows[family]:
        bs = ";".join("%s=%s" % (k, v[:46]) for k, v in r["base"].items()) or "-"
        bp = ";".join("%s=%s" % (k, v[:30]) for k, v in r["bpath"].items())
        print("  %-30s | %-16s | img=%-20s | model=%-22s | %s | %s %s"
              % (r["cfg"], r["agent"][:16], r["img"][:20], r["model"][:22], r["surface"], bs, ("| "+bp) if bp else ""))
