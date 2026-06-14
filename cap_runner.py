#!/usr/bin/env python3
"""
cap_runner.py — The decisive confound experiment (paper review R2, both reviewers).

The pilot/dose data show compressed runs derail (0 edits) with n_events~=61, i.e.
~30 agent iterations == OE_OH_MAX_ITER. So "0 edits under compression" may be an
ITERATION-CAP artifact (the agent loops until the cap, terminating before it
edits) rather than genuine context-state collapse. This 2x2 raises the cap:
  {compression off (noop) / on (llm max=8)} x {iter cap 30 (default) / 120 (4x)}.
If raising the cap RESCUES the compressed arm (it completes / edits files), the
"0 edits" headline is a cap artifact and must be reframed. If the compressed arm
STILL produces 0 edits at iter=120, that is evidence of genuine state collapse
(it loops forever, not merely runs out of budget).

Reuses diff_runner.run_one; overrides write_sut to vary OE_OH_MAX_ITER per cell
and raises OE_RUN_TIMEOUT so iterations (not wall-clock) are the binding cap.
Launch AFTER the dose run finishes (one docker job at a time).
"""
import sys, pathlib
SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
sys.path.insert(0, SRC)
import diff_runner as dr


def write_sut(c):
    it = c.get("iter", 30)
    y = f"""sut_id: oh_cap_{c['id']}
agent_name: openhands
image: {dr.IMG}
base_model: deepseek-v4-flash
proxy_url_in_container: {dr.PROXY}
proxy_url_local: {dr.PROXY}
container_env:
  OE_LITELLM_URL: "{dr.PROXY}"
  OE_LITELLM_KEY: "sk-litellm-virtual"
  OE_MODEL: "{dr.MODEL}"
  OE_RUN_TIMEOUT: "1500"
  OE_OH_MAX_ITER: "{it}"
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
    p = pathlib.Path(SRC + f"/configs/_cap_{c['id']}.yaml")
    p.write_text(y)
    return str(p)


dr.write_sut = write_sut                      # vary OE_OH_MAX_ITER per cell
# raise run_one's outer subprocess timeout so iter=120 runs are not wall-clock-killed
_orig_run_one = dr.run_one
dr.TASKS = ["h1_obs_logging", "h1_http_helper"]
dr.CONDITIONS = [
    {"id": "noop_i30",   "cond": "noop", "kf": 1, "mx": 0, "iter": 30},
    {"id": "noop_i120",  "cond": "noop", "kf": 1, "mx": 0, "iter": 120},
    {"id": "llm8_i30",   "cond": "llm",  "kf": 1, "mx": 8, "iter": 30},
    {"id": "llm8_i120",  "cond": "llm",  "kf": 1, "mx": 8, "iter": 120},
]
dr.N = 4
dr.WB = "/home/qyb/oe_work/ocd_cap"
dr.RESULTS = SRC + "/results/cap"

if __name__ == "__main__":
    sys.exit(dr.main())
