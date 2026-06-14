#!/usr/bin/env python3
"""
minimax_runner.py — Second-model replication (full-paper upgrade).

Replicates the within-OpenHands differential (noop vs LLM compression) with a
SECOND model, minimax-m2.7 (via 火山 ark -> anthropic -> strip chain on :4036),
holding task + harness fixed. If compression collapses task completion on a
second, different model too, the "harness-caused, not model-inherent" claim
generalizes beyond DeepSeek-V4-Flash. Reuses diff_runner.run_one; overrides the
proxy/model and SUT. Launch after the minimax smoke confirms it edits.
"""
import sys, pathlib
SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
sys.path.insert(0, SRC)
import diff_runner as dr

PROXY = "http://127.0.0.1:4036"   # strip -> ark-litellm -> 火山 minimax-m2.7
MODEL = "anthropic/minimax"


def write_sut(c):
    y = f"""sut_id: oh_mm_{c['id']}
agent_name: openhands
image: {dr.IMG}
base_model: minimax-m2.7
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
    p = pathlib.Path(SRC + f"/configs/_mm_{c['id']}.yaml")
    p.write_text(y)
    return str(p)


dr.write_sut = write_sut
dr.TASKS = ["h1_obs_logging", "h1_http_helper", "h1_dep_freeze"]
dr.CONDITIONS = [
    {"id": "noop",   "cond": "noop", "kf": 1, "mx": 0},
    {"id": "llm_m8", "cond": "llm",  "kf": 1, "mx": 8},
]
dr.N = 4
dr.WB = "/home/qyb/oe_work/ocd_mm"
dr.RESULTS = SRC + "/results/mm"

if __name__ == "__main__":
    sys.exit(dr.main())
