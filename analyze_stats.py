#!/usr/bin/env python3
"""Within-harness causal stats: paired McNemar on task-completion, keep0 (NoOp) vs each
lossy strength, paired by (task, rep). BH-FDR across harnesses. Reports discordant pairs
b/c, exact p, and the completion-rate drop. A harness is included only if its keep0
baseline completion exceeds a floor (else there is no completion to collapse)."""
import collections
import glob
import json
import math

RESULTS = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes/results/matrix"
BASE_FLOOR = 0.30          # keep0 completion must exceed this to be a valid subject
ORDER = ["keep12", "keep6", "keep3"]


def is_complete(r):
    if r.get("E_state") in ("wrong", "never_reached"):
        return False
    if r.get("C_violated"):
        return False
    ps = r.get("P_subgoals") or []
    if ps and not all(p.get("correct") for p in ps):
        return False
    return r.get("valid") == "valid"


def mcnemar_exact(b, c):
    """Exact two-sided McNemar = binomial test on the discordant pairs (p=0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
    return min(1.0, 2 * tail)


def bh_fdr(pairs):
    """pairs: list of (key, p). Returns {key: q}."""
    m = len(pairs)
    s = sorted(pairs, key=lambda kv: kv[1])
    q = {}
    prev = 1.0
    for i in range(m - 1, -1, -1):
        k, p = s[i]
        prev = min(prev, p * m / (i + 1))
        q[k] = prev
    return q


def main():
    runs = collections.defaultdict(dict)   # (harness,strength) -> {(task,rep): complete}
    harnesses = set()
    for fp in glob.glob(RESULTS + "/*.json"):
        try:
            r = json.loads(open(fp).read())
        except Exception:
            continue
        h, s, t, rep = r.get("harness"), r.get("strength"), r.get("task"), r.get("rep")
        if h is None:
            continue
        harnesses.add(h)
        runs[(h, s)][(t, rep)] = is_complete(r)

    rows, pvals = [], []
    for h in sorted(harnesses):
        base = runs.get((h, "keep0"), {})
        brate = sum(base.values()) / len(base) if base else 0.0
        for s in ORDER:
            trt = runs.get((h, s), {})
            keys = set(base) & set(trt)
            if not keys:
                continue
            b = sum(1 for k in keys if base[k] and not trt[k])   # keep0 done, lossy not
            c = sum(1 for k in keys if trt[k] and not base[k])   # lossy done, keep0 not
            p = mcnemar_exact(b, c)
            r0 = sum(base[k] for k in keys) / len(keys)
            r1 = sum(trt[k] for k in keys) / len(keys)
            rows.append(dict(h=h, s=s, n=len(keys), base=brate, r0=r0, r1=r1,
                             drop=r0 - r1, b=b, c=c, p=p))
            if brate > BASE_FLOOR and s == "keep3":
                pvals.append((h, p))
    q = bh_fdr(pvals)

    print(f"{'harness':12} {'vs':7} {'n':4} {'keep0%':7} {'lossy%':7} {'drop':6} {'b/c':9} {'p':10} {'q(k3)':8} incl")
    print("-" * 86)
    for r in rows:
        incl = "Y" if r["base"] > BASE_FLOOR else "excl(base<floor)"
        qv = q.get(r["h"], float('nan')) if r["s"] == "keep3" else float('nan')
        print(f"{r['h']:12} {r['s']:7} {r['n']:<4} {100*r['r0']:6.0f} {100*r['r1']:6.0f} "
              f"{100*r['drop']:6.0f} {r['b']:>3}/{r['c']:<4} {r['p']:.2e}  "
              f"{(f'{qv:.2e}' if qv==qv else '   -   '):8} {incl}")
    print(f"\nfloor={BASE_FLOOR}; included harnesses (keep0>floor): "
          f"{sorted({r['h'] for r in rows if r['base']>BASE_FLOOR})}")


if __name__ == "__main__":
    main()
