#!/usr/bin/env python3
"""Analyze the OCD matrix (results/matrix/*.json).

Per (harness, strength) computes, following Laban et al. (ICLR 2026):
  - completion rate  : fraction of runs that did the task correctly (E correct, C not
                       violated, all P subgoals satisfied)
  - mean score S     : 100 * mean of the 4-way recovery vector y (C/E/P/D)
  - Aptitude  A90    : 90th-percentile S  (best-case ceiling)
  - Unreliability U  : P90(S) - P10(S)    (spread between best and worst case)
  - E_state mix      : correct / wrong(forgot) / never_reached(quit)

Then the cross-harness verdict: per harness, the compression effect = completion at
keep0 (NoOp) minus completion at keep3 (aggressive), and the FULL ceiling for context.
"""
import collections
import glob
import json
import statistics

RESULTS = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes/results/matrix"
ORDER = ["full", "keep0", "keep12", "keep6", "keep3"]


def score_of(rec):
    """Continuous completion score S in [0,100] for the aptitude/unreliability split.
    Graded, and -- unlike a raw mean of the 4-way y -- NOT inflated by quitters
    (whose C/D default high): a run that never reaches the entity / does no subgoal
    scores low. S = 100 * mean(E_factor, P_cover), with E_factor from the E three-state
    and P_cover the subgoal-satisfaction fraction; falls back to C_recover for C-only
    tasks that carry no E and no P subgoals."""
    y = rec.get("y") or {}
    parts = []
    es = rec.get("E_state")
    if es in ("correct", "wrong", "never_reached"):
        parts.append({"correct": 1.0, "wrong": 0.5, "never_reached": 0.0}[es])
    ps = rec.get("P_subgoals") or []
    if ps:
        parts.append(sum(1 for p in ps if p.get("correct")) / len(ps))
    if parts:
        return 100.0 * (sum(parts) / len(parts))
    c = y.get("C_recover")                         # C-only task fallback
    if isinstance(c, (int, float)) and c == c:
        return 100.0 * c
    return 0.0


def is_complete(rec):
    if rec.get("E_state") not in ("correct", None):   # some C-only tasks have no E
        if rec.get("E_state") == "wrong" or rec.get("E_state") == "never_reached":
            return False
    if rec.get("C_violated"):
        return False
    ps = rec.get("P_subgoals") or []
    if ps and not all(p.get("correct") for p in ps):
        return False
    return rec.get("valid") == "valid"


def pctile(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    i = max(0, min(len(xs) - 1, int(round((q / 100.0) * (len(xs) - 1)))))
    return xs[i]


def main():
    cells = collections.defaultdict(list)   # (harness, strength) -> [rec]
    for fp in glob.glob(RESULTS + "/*.json"):
        try:
            r = json.loads(open(fp).read())
        except Exception:
            continue
        if "harness" in r and "strength" in r:
            cells[(r["harness"], r["strength"])].append(r)

    harnesses = sorted({h for (h, _) in cells})
    print(f"\n{'harness':12} {'cond':7} {'n':3} {'compl%':7} {'meanS':6} {'A90':5} {'U':5}  E:corr/wrong/never")
    print("-" * 78)
    summary = {}
    for h in harnesses:
        for s in ORDER:
            recs = cells.get((h, s))
            if not recs:
                continue
            n = len(recs)
            comp = 100.0 * sum(is_complete(r) for r in recs) / n
            S = [score_of(r) for r in recs]
            es = collections.Counter(r.get("E_state") for r in recs)
            meanS = statistics.mean(S) if S else 0
            A90, P10 = pctile(S, 90), pctile(S, 10)
            U = A90 - P10
            summary[(h, s)] = dict(n=n, compl=comp, meanS=meanS, A90=A90, U=U)
            print(f"{h:12} {s:7} {n:<3} {comp:6.1f} {meanS:6.1f} {A90:5.0f} {U:5.0f}  "
                  f"{es.get('correct',0)}/{es.get('wrong',0)}/{es.get('never_reached',0)}")

    print("\n=== cross-harness: compression effect (completion%) ===")
    print(f"{'harness':12} {'FULL':6} {'keep0':6} {'keep12':6} {'keep6':6} {'keep3':6}  {'k0-k3':6} verdict")
    for h in harnesses:
        row = {s: summary.get((h, s), {}).get("compl") for s in ORDER}
        k0 = row.get("keep0"); k3 = row.get("keep3")
        delta = (k0 - k3) if (k0 is not None and k3 is not None) else float("nan")
        verdict = "IMMUNE" if (delta == delta and delta < 15) else ("COLLAPSE" if delta == delta else "?")
        cells_s = " ".join(f"{(row.get(s) if row.get(s) is not None else float('nan')):6.1f}" for s in ORDER)
        print(f"{h:12} {cells_s}  {delta:6.1f} {verdict}")


if __name__ == "__main__":
    main()
