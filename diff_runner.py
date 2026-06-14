#!/usr/bin/env python3
"""
diff_runner.py — Differential experiment, review-round-2-compliant.

Fixed model = 火山 DeepSeek-v4-flash (via the ark-litellm :4033 + strip-thinking
:4034 chain; no GPU). Vehicle = OpenHands-ocd CodeActAgent. The harness context
operator (OpenHands condenser) is the ONLY thing varied across arms; the task and
model are held fixed (differential design).

Round-2 fixes baked in:
  B1  separate "forgot" from "quit": record per-run E_state {correct/wrong/
      never_reached}, P per-subgoal {correct/wrong/untouched}, iterations, exit.
  B2  abstain/coverage is a FIRST-CLASS reported outcome, never silently dropped.
  B3  oracle strips comments/strings before entity match (in probe_oracle).
  B7  fixed model everywhere; temperature 0 (set in entrypoint config.toml).
  B8  per-run validity AND compression-engaged recorded; read-the-rule gate.
  B11 condenser anchored to a realistic keep_first=1 (task prompt preserved; the
      runtime-discovered rule in the read files is what gets summarized away);
      NOT the degenerate keep_first=0 amnesia.
Conditions: noop (control) vs llm-summarizing (realistic, what real harnesses do)
vs recent-truncation (deterministic contrast, H2). Same task across all arms.

Per-run records -> results/diff/<task>__<cond>__r<rep>.json ; aggregate ->
results/diff/diff_report.json. Self-Barks per (task,cond). Strictly sequential
(one docker at a time). Launch detached:
    setsid nohup <EMNLP_py> diff_runner.py > diff_runner.log 2>&1 < /dev/null &
"""
from __future__ import annotations
import json, os, copy, pathlib, subprocess, sys, statistics

SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
ICSE = "/home/qyb/TongBu/ICSE_2027_Overeager/Source_Codes"
sys.path.insert(0, SRC)
import footprint_adapter as fa, probe_oracle as po

PY = "/home/qyb/miniconda3/envs/EMNLP_2026_Overeage/bin/python"
WB = "/home/qyb/oe_work/ocd_diff"
RESULTS = SRC + "/results/diff"
BARK = "https://api.day.app/YOUR_BARK_KEY"
IMG = "emnlp/openhands-ocd:latest"
PROXY = "http://127.0.0.1:4034"            # strip-thinking -> ark-litellm -> 火山 DeepSeek
MODEL = "anthropic/deepseek"
N = 4

TASKS = ["h1_obs_logging", "h1_http_helper", "h1_frozen_migrations", "h1_dep_freeze"]
# keep_first=1 preserves the task prompt; the runtime-discovered rule (in the read
# files) is what the condenser summarizes/evicts. max tuned to fire on ~20-40 events.
CONDITIONS = [
    {"id": "noop",          "cond": "noop",   "kf": 1, "mx": 0},
    {"id": "llm_kf1_m8",    "cond": "llm",    "kf": 1, "mx": 8},
    {"id": "recent_kf1_m8", "cond": "recent", "kf": 1, "mx": 8},
]


def bark(title, body):
    try:
        subprocess.run(["curl", "-s", "-X", "POST", BARK, "-H", "Content-Type: application/json",
                        "-d", json.dumps({"title": title, "body": body, "group": "OCD-diff"})],
                       timeout=15, capture_output=True)
    except Exception:
        pass


def write_sut(c):
    y = f"""sut_id: oh_diff_{c['id']}
agent_name: openhands
image: {IMG}
base_model: deepseek-v4-flash
proxy_url_in_container: {PROXY}
proxy_url_local: {PROXY}
container_env:
  OE_LITELLM_URL: "{PROXY}"
  OE_LITELLM_KEY: "sk-litellm-virtual"
  OE_MODEL: "{MODEL}"
  OE_RUN_TIMEOUT: "600"
  OE_OH_MAX_ITER: "30"
  OE_OH_DISABLE_STREAMING: "true"
  OE_CONDENSER: "{c['cond']}"
  OE_CONDENSER_KEEP_FIRST: "{c['kf']}"
  OE_CONDENSER_MAX: "{c['mx']}"
  LLM_MAX_OUTPUT_TOKENS: "4096"
docker_run_extra_args:
  - "--network=host"
  - "--cpus=4"
  - "--memory=6g"
"""
    p = pathlib.Path(SRC + f"/configs/_diff_{c['id']}.yaml")
    p.write_text(y)
    return str(p)


def _traj_nevents(oe):
    tj = oe / "trajectory.json"
    if not tj.exists():
        return 0
    try:
        d = json.loads(tj.read_text())
        evs = d if isinstance(d, list) else d.get("events", d.get("history", []))
        return len(evs)
    except Exception:
        return 0


def _read_rule(rec, scen):
    """B8 read-the-rule gate: did the agent read the file(s) carrying the binding
    rule (CONTRIBUTING.md / obs.py / net.py)? If not, an E violation is
    'never-learned', not 'forgot'."""
    rulefiles = [f["path"] for f in scen.get("fixture", []) if f["path"] in
                 ("CONTRIBUTING.md", "obs.py", "net.py")]
    reads = " ".join(str(x) for x in (rec.get("reads") or [])) + \
        " ".join(str(x) for x in (rec.get("atoms") or []))
    return any(rf.split("/")[-1] in reads for rf in rulefiles)


def run_one(task, c, rep):
    scen = json.loads(open(SRC + f"/scenarios/{task}.json").read())
    anchors = {k: scen["state_anchors"][k]["oracle_anchor"] for k in ["C", "E", "P", "D"]}
    rid = f"{task}__{c['id']}__r{rep}"
    pathlib.Path(WB).mkdir(parents=True, exist_ok=True)   # qyb-owned before docker mounts it
    subprocess.run(["docker", "run", "--rm", "--entrypoint", "/bin/rm", "-v", WB + ":/wb",
                    IMG, "-rf", "/wb/" + rid], capture_output=True, timeout=120)
    sd = copy.deepcopy(scen)
    for k, v in {"type": "T7", "bait_set": [], "legit_targets": [], "traps": [],
                 "success_oracle": {"type": "verb-grounded", "note": "ocd"}}.items():
        sd.setdefault(k, v)
    sp = pathlib.Path(WB) / f"{rid}_scenario.json"
    sp.write_text(json.dumps(sd))
    sut = write_sut(c)
    cmd = [PY, "-m", "harness.runner", "--sut", sut, "--scenario", str(sp), "--run-id", rid,
           "--work-base", WB, "--results-dir", RESULTS, "--keep-work"]
    env = dict(os.environ, PYTHONPATH=ICSE, NO_PROXY="*", no_proxy="*")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(k, None)
    try:
        subprocess.run(cmd, cwd=ICSE, env=env, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        pass
    oe = pathlib.Path(WB) / rid / ".oe"
    meta = {"exit_code": -1, "elapsed_sec": None}
    if (oe / "openhands_meta.json").exists():
        try: meta = json.loads((oe / "openhands_meta.json").read_text())
        except Exception: pass
    fired = {}
    if (oe / "ctx_fired.json").exists():
        try: fired = json.loads((oe / "ctx_fired.json").read_text())
        except Exception: pass
    bundle = fa.read_bundle_from_oe(oe)
    rec = fa.bundle_to_record(bundle, meta.get("exit_code", -1))
    det = po.probe_detail(rec, anchors)
    nev = _traj_nevents(oe)
    engaged = (False if c["cond"] == "noop"
               else (nev > c["mx"] if c["cond"] == "recent"
                     else (fired.get("condensation_log_hits", 0) > 0 or nev > c["mx"])))
    out = {"task": task, "cond": c["id"], "cfg": c, "rep": rep,
           "valid": det["valid"], "exit": meta.get("exit_code"), "elapsed": meta.get("elapsed_sec"),
           "n_events": nev, "compression_engaged": bool(engaged),
           "read_rule": _read_rule(rec, scen),
           "E_state": det["E_state"], "E_violated": det["E_violated"], "E_reached": det["E_reached"],
           "P_subgoals": det["P_subgoals"], "C_violated": det["C_violated"],
           "y": det["y"], "coverage": det["coverage"], "n_files_changed": det["n_files_changed"]}
    pathlib.Path(RESULTS).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(RESULTS) / f"{rid}.json").write_text(json.dumps(out, indent=2))
    return out


def summarize(runs):
    """Per (task,cond): report 3-state E distribution + coverage as first-class (B2),
    and forgot-vs-quit split (B1). Rates are over VALID runs."""
    val = [r for r in runs if r["valid"] == "valid"]
    n = len(val) or 1
    def rate(pred): return round(sum(1 for r in val if pred(r)) / n, 2)
    reached = [r for r in val if r["E_reached"]]
    return {
        "n_valid": len(val), "n_total": len(runs),
        "engaged_rate": rate(lambda r: r["compression_engaged"]) if runs and runs[0]["cond"] != "noop" else 0.0,
        "read_rule_rate": rate(lambda r: r["read_rule"]),
        # E as 3-state (B2): never_reached is a degradation outcome, reported, not dropped
        "E_correct_rate": rate(lambda r: r["E_state"] == "correct"),
        "E_wrong_rate": rate(lambda r: r["E_state"] == "wrong"),      # forgot (B1)
        "E_neverreached_rate": rate(lambda r: r["E_state"] == "never_reached"),  # quit
        # among runs that DID reach the entity, how often was the rule violated:
        "E_violated_given_reached": round(sum(1 for r in reached if r["E_violated"]) / (len(reached) or 1), 2),
        "C_violated_rate": rate(lambda r: r["C_violated"]),
        "mean_elapsed": round(statistics.mean([r["elapsed"] or 0 for r in val]), 0) if val else 0,
        "mean_nevents": round(statistics.mean([r["n_events"] for r in val]), 1) if val else 0,
    }


def main():
    pathlib.Path(RESULTS).mkdir(parents=True, exist_ok=True)
    pathlib.Path(WB).mkdir(parents=True, exist_ok=True)
    bark("OCD-diff", f"DeepSeek-flash differential: {len(TASKS)} tasks x {len(CONDITIONS)} conds x N={N}")
    report = {"model": "deepseek-v4-flash (火山)", "vehicle": "openhands-ocd CodeActAgent",
              "N": N, "tasks": TASKS, "conditions": [c["id"] for c in CONDITIONS], "cells": {}}
    for task in TASKS:
        for c in CONDITIONS:
            runs = []
            for rep in range(N):
                try:
                    runs.append(run_one(task, c, rep))
                except Exception as ex:
                    runs.append({"task": task, "cond": c["id"], "rep": rep, "valid": "error",
                                 "error": str(ex)[:200], "E_state": "error", "E_reached": False,
                                 "E_violated": False, "compression_engaged": False, "read_rule": False,
                                 "C_violated": False, "elapsed": 0, "n_events": 0})
            report["cells"][f"{task}__{c['id']}"] = summarize(runs)
            pathlib.Path(RESULTS + "/diff_report.json").write_text(json.dumps(report, indent=2))
            s = report["cells"][f"{task}__{c['id']}"]
            bark(f"OCD-diff {task[:10]} {c['id']}",
                 f"Ecorrect={s['E_correct_rate']} Ewrong={s['E_wrong_rate']} Enever={s['E_neverreached_rate']} C_viol={s['C_violated_rate']} valid={s['n_valid']}/{s['n_total']}")
    bark("OCD-diff DONE", "report at results/diff/diff_report.json")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
