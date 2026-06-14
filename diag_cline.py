#!/usr/bin/env python3
"""Why did cline reach the model + emit tool calls but land 0 files? Inspect its
NDJSON stream for the edit tool calls and their results, and diff fs_before/after."""
import json, glob, os, re, collections

base = sorted(glob.glob("/home/qyb/oe_work/ocd_matrix/cline__keep0__*"))
base = [b for b in base if os.path.isdir(b)]
d = base[0] + "/.oe"
print("dir:", d)

# 1. fs diff
try:
    b = json.load(open(d + "/fs_before.json")); a = json.load(open(d + "/fs_after.json"))
    ch = [k for k in a if a.get(k) != b.get(k)]
    new = [k for k in a if k not in b]
    print(f"fs_before={len(b)} fs_after={len(a)} changed_or_new={ch[:12]} new={new[:12]}")
except Exception as e:
    print("fs diff err:", e)

# 2. scan stream events
kinds = collections.Counter()
tools = collections.Counter()
errs = []
writes = []
for ln in open(d + "/cline_stream.jsonl", errors="replace"):
    ln = ln.strip()
    if not ln:
        continue
    try:
        o = json.loads(ln)
    except Exception:
        continue
    t = o.get("type") or o.get("say") or o.get("ask") or "?"
    kinds[str(t)] += 1
    blob = json.dumps(o, ensure_ascii=False)
    for tool in ("write_to_file", "replace_in_file", "new_file", "execute_command", "read_file", "list_files"):
        if tool in blob:
            tools[tool] += 1
    if re.search(r'error|failed|does not match|not found|No changes|invalid', blob, re.I):
        errs.append(blob[:240])
    if '"path"' in blob and ('write_to_file' in blob or 'replace_in_file' in blob):
        m = re.search(r'"path"\s*:\s*"([^"]+)"', blob)
        if m:
            writes.append(m.group(1))

print("event kinds:", dict(kinds.most_common(12)))
print("tool mentions:", dict(tools))
print("write target paths:", collections.Counter(writes).most_common(8))
print("error-ish lines:", len(errs))
for e in errs[:6]:
    print("  ERR>", e)
