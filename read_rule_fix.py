#!/usr/bin/env python3
"""
read_rule_fix.py — Re-derive the B8 manipulation check from saved trajectories.

The live diff_runner._read_rule looked in the bundle's parsed `reads` field, which
does NOT capture OpenHands' file-view actions; it returned False for every run
(read_rule=0/49), which the paper flagged as possibly a capture bug. The
trajectory.json DOES log file reads as events with action=="read" and the path in
the message. This re-scans trajectories to determine, per run, whether the
rule-bearing file(s) were actually read by the agent. Resolves "never-learned vs
forgot": if NoOp reads the rule and complies while a compressed arm reads it but
fails, that supports a forgetting interpretation; if neither reads it, the
mechanism is unconfirmed.
"""
import json, glob, sys
from collections import defaultdict

# rule-bearing files per task (where the runtime-discovered convention lives)
RULE_FILES = ["CONTRIBUTING.md", "obs.py", "net.py", "clock.py", "rngutil.py",
              "idgen.py", "settings.py", "db.py"]


def reads_in_traj(tj):
    try:
        d = json.load(open(tj))
    except Exception:
        return None  # trajectory missing/unflushed
    evs = d if isinstance(d, list) else d.get("events", d.get("history", []))
    read_paths = []
    for e in evs:
        if e.get("action") == "read" or e.get("observation") == "read":
            blob = str(e.get("message", "")) + " " + str(e.get("content", "")) + " " + json.dumps(e.get("args", {}))
            read_paths.append(blob)
    return read_paths


def read_rule(work_dir):
    tj = work_dir + "/.oe/trajectory.json"
    paths = reads_in_traj(tj)
    if paths is None:
        return "no_traj"
    hit = any(any(rf in p for rf in RULE_FILES) for p in paths)
    return "read" if hit else "no_read"


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "/home/qyb/oe_work/ocd_diff"
    rows = defaultdict(lambda: defaultdict(int))
    for wd in sorted(glob.glob(base + "/*/")):
        rid = wd.rstrip("/").split("/")[-1]
        if "scenario" in rid:
            continue
        # cond is the middle token: task__cond__rep
        parts = rid.split("__")
        cond = parts[1] if len(parts) >= 3 else rid
        rr = read_rule(wd.rstrip("/"))
        rows[cond][rr] += 1
    print("base:", base)
    for cond in sorted(rows, key=str):
        print("%-16s %s" % (cond, dict(rows[cond])))


if __name__ == "__main__":
    main()
