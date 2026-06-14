#!/usr/bin/env python3
"""Did cline/goose/pi/qwen ACTUALLY edit files on disk (work dir kept), even though
their .oe bundle lacks fs snapshots? Walk the host sandbox and look for the target
edit (print/logging -> log_event) and any modified .py files."""
import glob, os

for h in ["cline", "goose", "pi", "qwen"]:
    dirs = sorted(d for d in glob.glob(f"/home/qyb/oe_work/ocd_matrix/{h}__keep0__*") if os.path.isdir(d))
    if not dirs:
        print(f"\n#### {h}: no run dir"); continue
    sb = dirs[0] + "/sandbox"
    print(f"\n#### {h}  sandbox={sb}  exists={os.path.isdir(sb)}")
    if not os.path.isdir(sb):
        # maybe sandbox is elsewhere
        for root, _, _ in os.walk(dirs[0]):
            if root.endswith("/sandbox"):
                sb = root; print("  found sandbox at", sb); break
    hits = []
    pys = []
    for root, _, files in os.walk(sb):
        if "/.oe" in root or "/.git" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, sb)
            pys.append(rel)
            try:
                txt = open(p, errors="replace").read()
            except Exception:
                continue
            if "log_event(" in txt and "/svc/" not in p:
                # count log_event calls outside the obs.py definition site
                n = txt.count("log_event(")
                hits.append((rel, n))
    print(f"  .py files in sandbox: {len(pys)}")
    print(f"  files containing log_event(): {hits[:12]}")
