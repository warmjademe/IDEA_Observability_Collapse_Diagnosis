#!/usr/bin/env python3
"""
pilot_stage1.py — Stage-1 single-harness micro-pilot (self-contained, GPU-gated,
self-Barking). Verifies the FIRST gate the design review demanded before any full
campaign: H4 sensitivity — does perturbing a state component's presentation
redundancy move its recovery probe ABOVE the measurement-noise floor? If even that
fails, the whole observability story is moot and we must NOT scale to GPU-months.

Harness: mini-swe-agent (pure bash, zero blind spots — easiest to confirm the
context operator actually fires). Model: ollama devstral:24b via the OpenAI
surface. Runner: the ICSE harness runner (reused as-is; we ignore its overeager
verdict and recompute our four-way recovery scores from the kept .oe/ bundle).

Flow: wait for a free GPU -> SMOKE (one base run; abort+Bark if invalid) -> H4
ladder for components E and D over s in {1..5} (base=3), N repeats -> central /
one-sided slopes + symmetry + SNR gate -> save REPORT + Bark.

Run on the IDEA conda env (needs numpy); it shells out to the EMNLP env python to
drive the ICSE docker runner. Launch detached:
    setsid nohup <IDEA_py> pilot_stage1.py > pilot.log 2>&1 < /dev/null &
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import gpu_guard
import perturb
import footprint_adapter
import probe_oracle

HERE = pathlib.Path(__file__).resolve().parent
ICSE = pathlib.Path("/home/qyb/TongBu/ICSE_2027_Overeager/Source_Codes")
EMNLP_PY = "/home/qyb/miniconda3/envs/EMNLP_2026_Overeage/bin/python"
# aider (not mini-swe): aider uses whole-file/SEARCH-REPLACE text edits, NOT
# OpenAI tool-calling, so it works with ollama local models (mini-swe v2.3.0
# requires function-calling that ollama does not reliably emit). See IDEA doc.
SUT = HERE / "configs" / "aider_ollama.yaml"
CLEAN_IMAGE = "emnlp/aider:latest"
SCEN_FILE = HERE / "scenarios" / "pilot_auth_refactor.json"
WORK_BASE = pathlib.Path("/home/qyb/oe_work/ocd_pilot")
RESULTS = HERE / "results" / "stage1"
BARK = "https://api.day.app/YOUR_BARK_KEY"
N_REPEAT = 3
BASE = 3
COMPONENTS = ["E", "D"]
# devstral:24b needs ~15-16 GB; require headroom so we don't OOM next to others.
MIN_GPU_FREE_MIB = 15000


def bark(title: str, body: str) -> None:
    try:
        subprocess.run(["curl", "-s", "-X", "POST", BARK,
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps({"title": title, "body": body, "group": "OCD-pilot"})],
                       timeout=15, capture_output=True)
    except Exception:
        pass


def run_harness(scen_dict: dict, run_id: str):
    """Materialize a perturbed scenario, drive mini-swe via the ICSE runner with
    --keep-work, and return (probe record, tail-log). Adds dummy overeager fields
    so the runner's judge_run does not crash; its verdict is ignored."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    WORK_BASE.mkdir(parents=True, exist_ok=True)
    # The container runs as root and writes work_dir/.oe/.config (HOME=/workdir/.oe),
    # which the qyb host user cannot delete -> the ICSE runner's rmtree of a reused
    # run_id crashes with PermissionError before docker even starts. Clear this run's
    # work_dir as root via a throwaway container first.
    subprocess.run(["docker", "run", "--rm", "--entrypoint", "/bin/rm",
                    "-v", f"{WORK_BASE}:/wb", CLEAN_IMAGE,
                    "-rf", f"/wb/{run_id}"], capture_output=True, timeout=90)
    scen = dict(scen_dict)
    scen.setdefault("type", "T7")
    scen.setdefault("bait_set", [])
    scen.setdefault("legit_targets", [])
    scen.setdefault("traps", [])
    scen.setdefault("success_oracle", {"type": "verb-grounded", "note": "ocd-pilot"})
    sp = WORK_BASE / f"{run_id}_scenario.json"
    sp.write_text(json.dumps(scen))
    cmd = [EMNLP_PY, "-m", "harness.runner", "--sut", str(SUT), "--scenario", str(sp),
           "--run-id", run_id, "--work-base", str(WORK_BASE),
           "--results-dir", str(RESULTS), "--keep-work"]
    env = dict(os.environ, PYTHONPATH=str(ICSE))
    log = ""
    try:
        r = subprocess.run(cmd, cwd=str(ICSE), env=env, capture_output=True,
                           text=True, timeout=1000)
        log = (r.stdout or "")[-800:] + "\n--STDERR--\n" + (r.stderr or "")[-800:]
    except subprocess.TimeoutExpired:
        log = "outer timeout"
    ec = 0
    rj = RESULTS / f"{run_id}.json"
    if rj.exists():
        try:
            ec = json.loads(rj.read_text()).get("meta", {}).get("exit_code", 0)
        except Exception:
            pass
    bundle = footprint_adapter.read_bundle_from_oe(WORK_BASE / run_id / ".oe")
    rec = footprint_adapter.bundle_to_record(bundle, exit_code=ec)
    return rec, log


def _probe_value(vec, comp):
    """The recovery-probe scalar corresponding to the perturbed component."""
    idx = {"C": 0, "E": 1, "P": 2, "D": 3}[comp]
    return vec[idx]


def main() -> int:
    SCEN = json.loads(SCEN_FILE.read_text())
    anchors = perturb.oracle_anchors(SCEN)
    RESULTS.mkdir(parents=True, exist_ok=True)

    bark("OCD-pilot", "waiting for a free GPU (devstral:24b needs ~15GB)")
    ok = gpu_guard.wait_until_free(poll_interval=180, timeout=6 * 3600,
                                   min_gpu_free_mib=MIN_GPU_FREE_MIB,
                                   gpu_util_thresh=30, samples=4)
    if not ok:
        bark("OCD-pilot", "GPU wait timed out after 6h; aborting")
        return 4

    # ---- SMOKE: one base run must engage and be valid ----
    base_scen = perturb.perturb_scenario(SCEN, "E", BASE)
    rec, log = run_harness(base_scen, "smoke")
    sc = probe_oracle.recovery_scores(rec, anchors)
    (RESULTS / "smoke_debug.txt").write_text(log + "\n\nrecord:\n" + json.dumps(rec, indent=2)
                                             + "\n\nscores:\n" + json.dumps(sc.to_dict(), indent=2))
    bark("OCD-pilot-smoke", f"valid={sc.valid} y={ {k: round(v,2) if v==v else 'nan' for k,v in sc.y.items()} }")
    if sc.valid != "valid":
        bark("OCD-pilot", f"SMOKE INVALID ({sc.valid}); aborting — check harness/model wiring")
        return 3

    # ---- H4 ladder ----
    ladder = perturb.delta_ladder(base=BASE)  # [1,2,3,4,5]
    report = {"scenario": SCEN["id"], "harness": "mini_swe_agent_ollama",
              "model": "devstral:24b", "n_repeat": N_REPEAT, "base": BASE,
              "ladder": ladder, "components": {}}
    for comp in COMPONENTS:
        per_s = {s: [] for s in ladder}
        for rep in range(N_REPEAT):
            for s in ladder:
                rid = f"{comp}_s{s}_r{rep}"
                rec, _ = run_harness(perturb.perturb_scenario(SCEN, comp, s), rid)
                v = probe_oracle.recovery_scores(rec, anchors).vector()
                per_s[s].append(_probe_value(v, comp))
        # per-s mean of the component's own probe; noise SD from base-rung repeats
        means = {s: float(np.nanmean(per_s[s])) for s in ladder}
        noise_sd = float(np.nanstd(per_s[BASE], ddof=1)) if np.sum(~np.isnan(per_s[BASE])) > 1 else float("nan")
        # central + one-sided secants around base
        fwd = means[BASE + 1] - means[BASE]
        bwd = means[BASE] - means[BASE - 1]
        central = (means[BASE + 1] - means[BASE - 1]) / 2.0
        asym = abs(fwd - bwd) / max(abs(fwd) + abs(bwd), 1e-9)
        snr = abs(central) / noise_sd if noise_sd and noise_sd == noise_sd and noise_sd > 0 else float("inf") if abs(central) > 0 else 0.0
        h4_pass = (snr >= 2.0) and (asym <= 0.5)
        report["components"][comp] = {
            "means_by_s": means, "noise_sd": noise_sd,
            "fwd_slope": fwd, "bwd_slope": bwd, "central_slope": central,
            "asymmetry": asym, "snr": snr, "h4_pass": bool(h4_pass),
            "raw": {str(s): per_s[s] for s in ladder},
        }

    (RESULTS / "stage1_report.json").write_text(json.dumps(report, indent=2))
    summary = "; ".join(f"{c}: SNR={report['components'][c]['snr']:.1f} "
                        f"asym={report['components'][c]['asymmetry']:.2f} "
                        f"H4={'PASS' if report['components'][c]['h4_pass'] else 'FAIL'}"
                        for c in COMPONENTS)
    bark("OCD-pilot-DONE", summary)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
