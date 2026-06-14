#!/usr/bin/env python3
"""
analyze_diff.py — Statistics for the differential experiment (review B6/B9).

Reads the per-run records in results/diff/*.json and tests the H1 contrast:
holding model+task fixed, does turning on a harness context operator (condenser)
increase failure to apply the runtime-discovered rule?

Round-2-compliant choices:
  - DV is a per-run CATEGORICAL E_state {correct, wrong (forgot), never_reached
    (quit)}; we report all three rates per cell (B2: coverage/abstain first-class)
    and test components separately (B1: forgot vs quit are different stories).
  - Per (task, compressed-cond) vs noop: 2x2 Fisher exact on E_fail (=not correct),
    on E_wrong-among-reached (forgot), and on never_reached (quit). Effect = rate
    difference + odds ratio.
  - BH-FDR across the whole family of tests (B9).
  - Pooled (stratified-by-task) Mantel-Haenszel-style table for the headline,
    with the explicit caveat that pooling assumes task is the only stratifier.
Only VALID runs are used; for the "forgot" test we further condition on E_reached.
"""
from __future__ import annotations
import json, glob, sys, math
from collections import defaultdict

try:
    from scipy.stats import fisher_exact
except Exception:
    fisher_exact = None

SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
DIFF = SRC + "/results/diff"


def load_runs():
    runs = []
    for p in glob.glob(DIFF + "/*.json"):
        if p.endswith("diff_report.json"):
            continue
        try:
            runs.append(json.loads(open(p).read()))
        except Exception:
            pass
    return [r for r in runs if r.get("valid") == "valid"]


def bh_fdr(pvals):
    """Benjamini-Hochberg adjusted p-values."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    prev = 1.0
    for rank, i in enumerate(reversed(order)):
        k = m - rank
        val = min(prev, pvals[i] * m / k)
        adj[i] = val
        prev = val
    return adj


def two_by_two(noop_runs, cond_runs, predicate):
    """Returns (a,b,c,d): a=cond&fail, b=cond&ok, c=noop&fail, d=noop&ok."""
    a = sum(1 for r in cond_runs if predicate(r))
    b = len(cond_runs) - a
    c = sum(1 for r in noop_runs if predicate(r))
    d = len(noop_runs) - c
    return a, b, c, d


def fisher(a, b, c, d):
    if fisher_exact is None:
        return None, None
    try:
        odds, p = fisher_exact([[a, b], [c, d]])
        return odds, p
    except Exception:
        return None, None


def rate(runs, predicate):
    n = len(runs)
    return (sum(1 for r in runs if predicate(r)) / n) if n else float("nan"), len(runs)


def main():
    runs = load_runs()
    if not runs:
        print("no valid runs yet"); return
    by = defaultdict(list)
    for r in runs:
        by[(r["task"], r["cond"])].append(r)
    tasks = sorted({t for t, _ in by})
    conds = sorted({c for _, c in by})
    compressed = [c for c in conds if c != "noop"]

    is_fail = lambda r: r["E_state"] != "correct"          # forgot OR quit
    is_wrong = lambda r: r["E_state"] == "wrong"           # forgot (touched, wrong token)
    is_never = lambda r: r["E_state"] == "never_reached"   # quit

    # ---- per-cell descriptive (3-state E + coverage + C) ----
    print("=" * 96)
    print("PER-CELL E 3-STATE (rates over valid runs)   [correct=remembered  wrong=forgot  never=quit]")
    print("%-22s %-14s  corr  wrong never  C_viol  reached  n" % ("task", "cond"))
    for t in tasks:
        for c in conds:
            rs = by.get((t, c), [])
            if not rs: continue
            fr = lambda pred: round(rate(rs, pred)[0], 2)
            reached = round(rate(rs, lambda r: r["E_reached"])[0], 2)
            print("%-22s %-14s  %.2f  %.2f  %.2f   %.2f    %.2f    %d" %
                  (t[:22], c, fr(lambda r: r["E_state"] == "correct"), fr(is_wrong),
                   fr(is_never), fr(lambda r: r.get("C_violated")), reached, len(rs)))

    # ---- inferential: each compressed cond vs noop, per task + pooled ----
    tests = []  # (label, a,b,c,d, odds, p)
    pooled = defaultdict(lambda: [0, 0, 0, 0])  # cond -> summed 2x2 over tasks, for E_fail
    for t in tasks:
        noop = by.get((t, "noop"), [])
        if not noop: continue
        for c in compressed:
            cr = by.get((t, c), [])
            if not cr: continue
            for oname, pred, restrict in [("E_fail", is_fail, None),
                                           ("E_wrong|reached", is_wrong, "reached"),
                                           ("never_reached", is_never, None)]:
                nn = [r for r in noop if r["E_reached"]] if restrict == "reached" else noop
                cc = [r for r in cr if r["E_reached"]] if restrict == "reached" else cr
                if not nn or not cc: continue
                a, b, cc2, d = two_by_two(nn, cc, pred)
                odds, p = fisher(a, b, cc2, d)
                tests.append({"task": t, "cond": c, "outcome": oname,
                              "cond_fail_rate": round(a / (a + b), 2) if a + b else None,
                              "noop_fail_rate": round(cc2 / (cc2 + d), 2) if cc2 + d else None,
                              "odds": None if odds is None else round(odds, 2),
                              "p": None if p is None else p})
                if oname == "E_fail":
                    pv = pooled[c]
                    pv[0] += a; pv[1] += b; pv[2] += cc2; pv[3] += d
    # BH-FDR over all tests that have a p
    have_p = [tt for tt in tests if tt["p"] is not None]
    if have_p:
        adj = bh_fdr([tt["p"] for tt in have_p])
        for tt, q in zip(have_p, adj):
            tt["p_bh"] = q
    print("\n" + "=" * 96)
    print("PER-(task,cond) vs noop  [BH-FDR adjusted]   * = q<0.05")
    print("%-20s %-13s %-16s noop->cond  odds   p      q" % ("task", "cond", "outcome"))
    for tt in tests:
        star = "*" if tt.get("p_bh") is not None and tt["p_bh"] < 0.05 else " "
        print("%-20s %-13s %-16s %s->%s   %-5s  %-6s %-6s %s" % (
            tt["task"][:20], tt["cond"], tt["outcome"],
            tt["noop_fail_rate"], tt["cond_fail_rate"], tt["odds"],
            ("%.3f" % tt["p"]) if tt["p"] is not None else "na",
            ("%.3f" % tt["p_bh"]) if tt.get("p_bh") is not None else "na", star))

    # ---- pooled (stratified by task) headline for E_fail ----
    print("\n" + "=" * 96)
    print("POOLED across tasks (E_fail = forgot-or-quit; caveat: pooling assumes task is the only stratifier)")
    for c in compressed:
        a, b, cc2, d = pooled[c]
        odds, p = fisher(a, b, cc2, d)
        cr = a / (a + b) if a + b else float("nan")
        nr = cc2 / (cc2 + d) if cc2 + d else float("nan")
        print("  noop vs %-13s  E_fail: noop=%.2f cond=%.2f  OR=%s  p=%s" % (
            c, nr, cr, "na" if odds is None else round(odds, 2),
            "na" if p is None else ("%.4f" % p)))

    out = {"tests": tests, "pooled": {c: pooled[c] for c in compressed},
           "n_valid_runs": len(runs)}
    open(DIFF + "/diff_stats.json", "w").write(json.dumps(out, indent=2))
    print("\nsaved", DIFF + "/diff_stats.json")


if __name__ == "__main__":
    main()
