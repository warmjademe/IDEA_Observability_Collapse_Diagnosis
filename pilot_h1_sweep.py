#!/usr/bin/env python3
"""
pilot_h1_sweep.py — H1 dose-response micro-pilot (self-contained, GPU-gated,
self-Barking, incremental-save).

Question (H1): holding MODEL and TASK fixed, does flipping/intensifying the
harness's context-compression operator causally degrade the four-way recovery
scores? Vehicle: OpenHands (multi-turn CodeActAgent) + qwen3-coder:30b (a local
model verified to act in this loop) + the openhands-ocd [condenser] knob. Same
image, same task, only the condenser config varies across conditions.

Conditions sweep the operator from OFF to aggressive, and contrast deterministic
truncation (recent) vs lossy summarization (llm), and prompt-kept (keep_first=1)
vs prompt-droppable (keep_first=0). u_t (did compression engage) is recorded per
run: for recent, truncation engaged iff trajectory n_events > max_events; for
llm, ctx_fired log hits > 0.

Each run reuses the ICSE runner with --keep-work; the four-way oracle is recomputed
from the kept .oe bundle (fs diff + file_after content), robust to the empty event
store on SIGTERM-timeout runs. Runs are STRICTLY SEQUENTIAL (one docker at a time)
per the NAS overload rule. Launch detached:
    setsid nohup <EMNLP_py> pilot_h1_sweep.py > h1_sweep.log 2>&1 < /dev/null &
"""
from __future__ import annotations
import json, os, pathlib, subprocess, sys, statistics

SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
ICSE = "/home/qyb/TongBu/ICSE_2027_Overeager/Source_Codes"
sys.path.insert(0, SRC)
import perturb, footprint_adapter as fa, probe_oracle as po
import gpu_guard

PY = "/home/qyb/miniconda3/envs/EMNLP_2026_Overeage/bin/python"
SCEN = json.loads(open(SRC + "/scenarios/pilot_auth_refactor.json").read())
ANCHORS = {k: SCEN["state_anchors"][k]["oracle_anchor"] for k in ["C", "E", "P", "D"]}
WB = "/home/qyb/oe_work/ocd_h1"
RESULTS = SRC + "/results/h1"
BARK = "https://api.day.app/YOUR_BARK_KEY"
IMG = "emnlp/openhands-ocd:latest"
PROXY = "http://127.0.0.1:4032"
MODEL = "anthropic/qwen3coder"
N = 3
MIN_GPU_FREE_MIB = 15000

CONDITIONS = [
    {"id": "noop",          "cond": "noop",   "kf": 1, "mx": 0},
    {"id": "recent_kf1_m6", "cond": "recent", "kf": 1, "mx": 6},
    {"id": "recent_kf1_m3", "cond": "recent", "kf": 1, "mx": 3},
    {"id": "recent_kf0_m6", "cond": "recent", "kf": 0, "mx": 6},
    {"id": "recent_kf0_m3", "cond": "recent", "kf": 0, "mx": 3},
    {"id": "llm_kf1_m6",    "cond": "llm",    "kf": 1, "mx": 6},
]


def bark(title, body):
    try:
        subprocess.run(["curl", "-s", "-X", "POST", BARK, "-H", "Content-Type: application/json",
                        "-d", json.dumps({"title": title, "body": body, "group": "OCD-H1"})],
                       timeout=15, capture_output=True)
    except Exception:
        pass


def write_sut(c):
    y = f"""sut_id: oh_h1_{c['id']}
agent_name: openhands
image: {IMG}
base_model: qwen3-coder:30b
proxy_url_in_container: {PROXY}
proxy_url_local: {PROXY}
container_env:
  OE_LITELLM_URL: "{PROXY}"
  OE_LITELLM_KEY: "sk-litellm-virtual"
  OE_MODEL: "{MODEL}"
  OE_RUN_TIMEOUT: "700"
  OE_OH_MAX_ITER: "20"
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
    p = pathlib.Path(SRC + f"/configs/_h1_{c['id']}.yaml")
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


def run_one(c, rep):
    rid = f"{c['id']}_r{rep}"
    subprocess.run(["docker", "run", "--rm", "--entrypoint", "/bin/rm", "-v", WB + ":/wb",
                    IMG, "-rf", "/wb/" + rid], capture_output=True, timeout=120)
    scen = perturb.perturb_scenario(SCEN, "E", 3)
    for k, v in {"type": "T7", "bait_set": [], "legit_targets": [], "traps": [],
                 "success_oracle": {"type": "verb-grounded", "note": "ocd"}}.items():
        scen.setdefault(k, v)
    sp = pathlib.Path(WB) / f"{rid}_scenario.json"
    sp.write_text(json.dumps(scen))
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
    nev = _traj_nevents(oe)
    sc = {}
    for k, fn in [("C", po.score_C), ("E", po.score_E), ("P", po.score_P), ("D", po.score_D)]:
        v, n = fn(rec, ANCHORS)
        sc[k] = v if v == v else None
    # u_t: did compression engage this run?
    if c["cond"] == "noop":
        engaged = False
    elif c["cond"] == "recent":
        engaged = nev > c["mx"]            # truncation bit iff history exceeded window
    else:                                   # llm
        engaged = fired.get("condensation_log_hits", 0) > 0 or nev > c["mx"]
    return {"rid": rid, "scores": sc, "valid": po.validity(rec), "acted": po.acted(rec),
            "exit": meta.get("exit_code"), "elapsed": meta.get("elapsed_sec"),
            "n_events": nev, "compression_engaged": bool(engaged),
            "fs_mod": rec["fs_modified"], "fs_add": rec["fs_added"]}


def agg(runs, k):
    xs = [r["scores"][k] for r in runs if r["scores"].get(k) is not None]
    if not xs:
        return [None, None, 0]
    return [round(statistics.mean(xs), 3), round(statistics.pstdev(xs), 3), len(xs)]


def main():
    pathlib.Path(RESULTS).mkdir(parents=True, exist_ok=True)
    pathlib.Path(WB).mkdir(parents=True, exist_ok=True)
    bark("OCD-H1", "GPU wait then sweep: %d conds x N=%d (qwen3/OpenHands)" % (len(CONDITIONS), N))
    ok = gpu_guard.wait_until_free(poll_interval=180, timeout=6 * 3600,
                                   min_gpu_free_mib=MIN_GPU_FREE_MIB, gpu_util_thresh=30, samples=3)
    if not ok:
        bark("OCD-H1", "GPU wait timed out 6h; abort")
        return 4
    report = {"model": "qwen3-coder:30b", "task": SCEN["id"], "N": N,
              "vehicle": "openhands-ocd CodeActAgent", "conditions": {}}
    for c in CONDITIONS:
        runs = []
        for rep in range(N):
            try:
                runs.append(run_one(c, rep))
            except Exception as e:
                runs.append({"rid": f"{c['id']}_r{rep}", "error": str(e)[:200],
                             "scores": {}, "valid": "error", "acted": False,
                             "n_events": 0, "compression_engaged": False})
        good = [r for r in runs if "error" not in r]
        report["conditions"][c["id"]] = {
            "cfg": c,
            "C": agg(good, "C"), "E": agg(good, "E"), "P": agg(good, "P"), "D": agg(good, "D"),
            "valid_rate": round(sum(1 for r in good if r.get("valid") == "valid") / max(len(good), 1), 2),
            "compression_engaged_rate": round(sum(1 for r in good if r.get("compression_engaged")) / max(len(good), 1), 2),
            "mean_nevents": round(statistics.mean([r["n_events"] for r in good]), 1) if good else 0,
            "mean_elapsed": round(statistics.mean([r["elapsed"] or 0 for r in good]), 0) if good else 0,
            "runs": runs,
        }
        pathlib.Path(RESULTS + "/h1_sweep_report.json").write_text(json.dumps(report, indent=2))
        cc = report["conditions"][c["id"]]
        bark("OCD-H1 " + c["id"], "E=%s P=%s C=%s valid=%s compr=%s nev=%s" %
             (cc["E"], cc["P"], cc["C"], cc["valid_rate"], cc["compression_engaged_rate"], cc["mean_nevents"]))
    bark("OCD-H1 DONE", "report at results/h1/h1_sweep_report.json")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
