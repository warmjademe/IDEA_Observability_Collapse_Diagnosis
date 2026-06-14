#!/usr/bin/env python3
"""
dose_runner.py — Dose-response over condenser strength (review B11 + pilot finding).

The pilot showed max_events/max_size=8 is TOO aggressive on ~40-event tasks: every
compressed run derails to never_reached, so we cannot see the 'completes-but-forgot-
the-rule' (E=wrong) regime that H2 needs. This sweeps the LLM-summarizing condenser
strength from mild to aggressive on the 3 working tasks to map the full curve:
  correct (remembered) -> wrong (forgot the rule, still completed) -> never_reached (derailed).

Reuses diff_runner's run_one/summarize (fixed DeepSeek-flash via the strip chain,
probe_detail capture). Separate results/work dirs so the pilot is untouched.
Launch: setsid nohup <EMNLP_py> dose_runner.py > dose_runner.log 2>&1 < /dev/null &
"""
import sys, json, pathlib, statistics
SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
sys.path.insert(0, SRC)
import diff_runner as dr

dr.TASKS = ["h1_obs_logging", "h1_http_helper", "h1_dep_freeze"]
dr.CONDITIONS = [{"id": "noop", "cond": "noop", "kf": 1, "mx": 0}] + \
    [{"id": f"llm_m{m}", "cond": "llm", "kf": 1, "mx": m} for m in (25, 18, 12, 8, 6)]
dr.N = 3
dr.WB = "/home/qyb/oe_work/ocd_dose"
dr.RESULTS = SRC + "/results/dose"

if __name__ == "__main__":
    sys.exit(dr.main())
