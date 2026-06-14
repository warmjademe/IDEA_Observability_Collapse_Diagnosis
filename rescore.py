#!/usr/bin/env python3
"""Re-score all kept run dirs with the ground-truth disk scorer (scoring.py), to
validate that the harnesses whose entrypoints skip fs-snapshots (cline/goose/pi/qwen)
actually completed the task. No agent re-run -- reads the kept work dirs only."""
import glob
import json
import os
import sys

sys.path.insert(0, "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes")
import scoring

SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
WB = "/home/qyb/oe_work/ocd_matrix"

scen_cache = {}


def load_scen(task):
    if task not in scen_cache:
        scen_cache[task] = json.loads(open(f"{SRC}/scenarios/{task}.json").read())
    return scen_cache[task]


rows = []
for d in sorted(glob.glob(WB + "/*__*__*__r*")):
    if not os.path.isdir(d):
        continue
    name = os.path.basename(d)
    try:
        harness, strength, task, rep = name.split("__")
    except ValueError:
        continue
    scen = load_scen(task)
    anchors = {k: scen["state_anchors"][k]["oracle_anchor"] for k in ["C", "E", "P", "D"]}
    try:
        det = scoring.score(d, scen, anchors)
        rows.append((harness, strength, task, det.get("valid"), det.get("E_state"),
                     det.get("C_violated"), det.get("n_files_changed")))
    except Exception as e:
        rows.append((harness, strength, task, "ERR", str(e)[:60], "", ""))

rows.sort()
print(f"{'harness':12} {'strength':8} {'task':18} {'valid':22} {'E_state':14} Cviol files")
for r in rows:
    print(f"{r[0]:12} {r[1]:8} {r[2]:18} {str(r[3]):22} {str(r[4]):14} {str(r[5]):5} {r[6]}")
