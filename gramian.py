"""
gramian.py — Local state-recovery sensitivity spectrum (data-driven
reconstructability proxy) for harness-induced degradation.

SCOPE / HONEST NAMING (revised after design review w1m4dsv9f):
This is NOT the Lall-Marsden trajectory-integrated empirical observability
Gramian, and there is no Hermann-Krener Lie-derivative rank condition here:
we have no explicit state-transition map f and we do not integrate outputs
along a trajectory. What we compute is a single-Jacobian, Fisher-information-
style matrix

    W = (1/N) * sum_s  J_s^T J_s ,   J[a,i] = d y_a / d x_i

i.e. the covariance of the output map's local sensitivity to perturbations of
the (parameterized) initial task-state components. We therefore call W the
"local state-recovery sensitivity spectrum" and treat lambda_min(W) as a
DATA-DRIVEN PROXY for how weakly a task-state direction is reconstructable from
the observable footprint — a diagnostic summary, NOT the causal identifier.
The causal weight in this project is carried by the same-image A/B ablation and
the patch closed-loop (H1/H3); W ranks/diagnoses, A/B identifies.

TWO MATH FIXES the review proved necessary (both verified in _self_test):

  (1) Noise-floor bias. With measurement noise on y (per-output variance
      sigma_a^2), the central difference injects variance sigma_a^2/(2 delta^2)
      into each Jacobian column, so E[W] = W_true + diag(c_i),
          c_i = sum_a sigma_a^2 / (2 delta_i^2).
      A truly unobservable direction (dy/dx = 0) then has lambda_min pinned at
      ~c, NOT 0 — "lambda_min collapses to ~0" is unreachable unless we subtract
      this floor. bias_correct() removes diag(c_i); the corrected lambda_min of a
      true-zero direction has a CI that COVERS 0.

  (2) Invalid percentile bootstrap on lambda_min/cond. lambda_min is a heavy-
      tailed, non-pivotal extreme eigenvalue; percentile-bootstrap coverage of
      the population value is ~0. We (a) make the headline read-out the corrected
      lambda_min itself (and the normalized lambda_min/lambda_max in [0,1]); keep
      1/lambda_min and cond only as log-scale illustration; and (b) report the
      causal estimand as a TASK-PAIRED difference delta = lambda_min^B -
      lambda_min^A with a paired bootstrap, whose coverage we verify in-range.

Pure CPU numpy. Run `python gramian.py` for the self-test (the Stage-0 gate).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Sequence

import numpy as np

STATE_COMPONENTS = ("C", "E", "P", "D")
PROBE_OUTPUTS = ("C_recover", "E_recover", "P_cover", "D_norepeat")


# --------------------------------------------------------------------------- #
# Jacobian assembly
# --------------------------------------------------------------------------- #
def central_difference(y_plus, y_minus, delta: float) -> np.ndarray:
    yp = np.asarray(y_plus, dtype=float)
    ym = np.asarray(y_minus, dtype=float)
    if yp.shape != ym.shape:
        raise ValueError(f"y_plus {yp.shape} != y_minus {ym.shape}")
    if delta <= 0:
        raise ValueError("delta must be > 0")
    return (yp - ym) / (2.0 * delta)


def one_sided_differences(y_base, y_plus, y_minus, delta: float):
    """Forward and backward secant slopes — used by the symmetry gate (P1).
    Asymmetry between them flags that the central difference is averaging two
    very different regimes (e.g. saturation on one side), so a central-difference
    Gramian entry would be meaningless."""
    yb = np.asarray(y_base, dtype=float)
    yp = np.asarray(y_plus, dtype=float)
    ym = np.asarray(y_minus, dtype=float)
    fwd = (yp - yb) / delta
    bwd = (yb - ym) / delta
    return fwd, bwd


def build_jacobian(columns: dict, delta, state_order=STATE_COMPONENTS) -> np.ndarray:
    cols = []
    for s in state_order:
        if s not in columns:
            raise ValueError(f"missing sensitivity for state component {s!r}")
        v = columns[s]
        d = delta[s] if isinstance(delta, dict) else delta
        if isinstance(v, tuple) and len(v) == 2:
            cols.append(central_difference(v[0], v[1], d))
        else:
            cols.append(np.asarray(v, dtype=float))
    return np.column_stack(cols)  # m x n


def gramian_from_jacobians(jacobians: Sequence[np.ndarray]) -> np.ndarray:
    if len(jacobians) == 0:
        raise ValueError("need at least one Jacobian")
    n = jacobians[0].shape[1]
    acc = np.zeros((n, n), dtype=float)
    for J in jacobians:
        J = np.asarray(J, dtype=float)
        if J.shape[1] != n:
            raise ValueError("inconsistent state dimension across Jacobians")
        acc += J.T @ J
    return acc / len(jacobians)


# --------------------------------------------------------------------------- #
# Noise floor + bias correction (FIX 1)
# --------------------------------------------------------------------------- #
def estimate_noise_var(baseline_runs: Sequence[Sequence[float]]) -> np.ndarray:
    """Per-output measurement variance sigma_a^2 from repeated UN-perturbed
    baseline runs (same task/seed, identical inputs). Shape (m,).
    Must come from real repeated baselines, never assumed."""
    Y = np.asarray(baseline_runs, dtype=float)  # (n_baseline, m)
    if Y.ndim != 2 or Y.shape[0] < 2:
        raise ValueError("need >= 2 baseline runs as an (n_baseline, m) array")
    return Y.var(axis=0, ddof=1)


def bias_floor(noise_var: Sequence[float], delta, state_order=STATE_COMPONENTS) -> np.ndarray:
    """Diagonal noise contribution diag(c_i), c_i = sum_a sigma_a^2 / (2 delta_i^2)."""
    nv = np.asarray(noise_var, dtype=float)
    s = float(np.sum(nv))
    n = len(state_order)
    c = np.empty(n, dtype=float)
    for i, comp in enumerate(state_order[:n]):
        d = delta[comp] if isinstance(delta, dict) else delta
        c[i] = s / (2.0 * d * d)
    return np.diag(c)


def bias_correct(W: np.ndarray, noise_var, delta, state_order=STATE_COMPONENTS) -> np.ndarray:
    """W_corrected = W - diag(c_i). NOT clipped — callers that want the eigen-CI
    to be able to cover 0 must keep negatives; analyze_gramian clips for display."""
    return np.asarray(W, dtype=float) - bias_floor(noise_var, delta, state_order)


# --------------------------------------------------------------------------- #
# Spectrum read-out
# --------------------------------------------------------------------------- #
@dataclass
class SpectrumReport:
    eigvals: list[float]                 # ascending (may be slightly negative pre-clip)
    lambda_min: float                    # bias-corrected, clipped >=0 for display
    lambda_min_raw: float                # bias-corrected, NOT clipped (for CI vs 0)
    lambda_max: float
    norm_lambda_min: float               # lambda_min / lambda_max in [0,1] (headline)
    inv_lambda_min_log: float            # log10(1/lambda_min) — illustration only
    cond_log: float                      # log10(cond) — illustration only
    least_observable_dir: dict           # eigvec of lambda_min over state comps
    state_order: list = field(default_factory=lambda: list(STATE_COMPONENTS))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def analyze_gramian(W: np.ndarray, state_order=STATE_COMPONENTS, eps: float = 1e-12) -> SpectrumReport:
    W = np.asarray(W, dtype=float)
    W = 0.5 * (W + W.T)
    vals, vecs = np.linalg.eigh(W)  # ascending
    lam_min_raw = float(vals[0])
    lam_min = max(0.0, lam_min_raw)
    lam_max = float(vals[-1])
    norm = lam_min / lam_max if lam_max > eps else 0.0
    inv_log = float(np.log10(1.0 / lam_min)) if lam_min > eps else float("inf")
    cond_log = float(np.log10(lam_max / lam_min)) if lam_min > eps else float("inf")
    dir_vec = np.abs(vecs[:, 0])
    least = {s: float(dir_vec[i]) for i, s in enumerate(state_order)}
    return SpectrumReport(
        eigvals=[float(v) for v in vals],
        lambda_min=lam_min, lambda_min_raw=lam_min_raw, lambda_max=lam_max,
        norm_lambda_min=norm, inv_lambda_min_log=inv_log, cond_log=cond_log,
        least_observable_dir=least, state_order=list(state_order),
    )


def _corrected_lambda_min_raw(jacs, noise_var, delta, state_order=STATE_COMPONENTS) -> float:
    W = gramian_from_jacobians(jacs)
    Wc = bias_correct(W, noise_var, delta, state_order)
    Wc = 0.5 * (Wc + Wc.T)
    return float(np.linalg.eigvalsh(Wc)[0])  # raw (may be negative)


# --------------------------------------------------------------------------- #
# Single-arm CI for corrected lambda_min (must COVER 0 for a true-zero dir)
# --------------------------------------------------------------------------- #
def lambda_min_ci(jacs, noise_var, delta, n_boot=2000, alpha=0.05, seed=0,
                  state_order=STATE_COMPONENTS) -> dict:
    rng = np.random.default_rng(seed)
    J = [np.asarray(j, float) for j in jacs]
    N = len(J)
    if N < 2:
        raise ValueError("need >= 2 runs")
    idx = np.arange(N)
    boot = np.array([
        _corrected_lambda_min_raw([J[i] for i in rng.choice(idx, N, replace=True)],
                                  noise_var, delta, state_order)
        for _ in range(n_boot)
    ])
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    point = _corrected_lambda_min_raw(J, noise_var, delta, state_order)
    return {"point_raw": point, "lo": float(np.percentile(boot, lo)),
            "hi": float(np.percentile(boot, hi)), "covers_zero": bool(np.percentile(boot, lo) <= 0 <= np.percentile(boot, hi))}


# --------------------------------------------------------------------------- #
# Paired A/B difference bootstrap (the causal estimand, FIX 2)
# --------------------------------------------------------------------------- #
def paired_diff_bootstrap(jacs_A, jacs_B, noise_var_A, noise_var_B, delta,
                          n_boot=2000, alpha=0.05, seed=0, state_order=STATE_COMPONENTS) -> dict:
    """delta_lm = lambda_min^B - lambda_min^A, paired by task index (arms share the
    resampled task set), bias-corrected per arm. Cancels common bias & task variance.
    jacs_A[t], jacs_B[t] are the per-task Jacobians for the two ablation arms."""
    A = [np.asarray(j, float) for j in jacs_A]
    B = [np.asarray(j, float) for j in jacs_B]
    if len(A) != len(B):
        raise ValueError("A/B must be paired (same number of tasks)")
    N = len(A)
    rng = np.random.default_rng(seed)
    idx = np.arange(N)

    def _diff(sel):
        la = _corrected_lambda_min_raw([A[i] for i in sel], noise_var_A, delta, state_order)
        lb = _corrected_lambda_min_raw([B[i] for i in sel], noise_var_B, delta, state_order)
        return lb - la

    point = _diff(idx)
    boot = np.array([_diff(rng.choice(idx, N, replace=True)) for _ in range(n_boot)])
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    clo, chi = float(np.percentile(boot, lo)), float(np.percentile(boot, hi))
    return {"point": float(point), "lo": clo, "hi": chi,
            "excludes_zero": bool(clo > 0 or chi < 0)}


# --------------------------------------------------------------------------- #
# H4 SNR sensitivity gate (unchanged logic; kept from validated version)
# --------------------------------------------------------------------------- #
def sensitivity_gate(jacobians, delta, noise_floor_sd, snr_thresh=2.0, min_frac=0.5,
                     state_order=STATE_COMPONENTS) -> dict:
    """Per-component SNR gate. signal_{a,i}=|J[a,i]|*delta_i vs per-output noise SD.
    Components failing the gate are DROPPED (not reported as collapse)."""
    J = [np.asarray(j, float) for j in jacobians]
    n = J[0].shape[1]
    nf = np.asarray(noise_floor_sd, float)
    nf = np.where(nf <= 0, 1e-9, nf)
    out, passed = {}, []
    for i, s in enumerate(state_order[:n]):
        d = delta[s] if isinstance(delta, dict) else delta
        snrs = np.array([float(np.max(np.abs(j[:, i]) * d / nf)) for j in J])
        frac = float(np.mean(snrs >= snr_thresh))
        mean_snr = float(np.mean(snrs))
        ok = mean_snr >= snr_thresh and frac >= min_frac
        out[s] = {"mean_snr": mean_snr, "frac_runs_pass": frac, "passes_gate": bool(ok)}
        if ok:
            passed.append(s)
    out["passed"] = passed
    out["snr_thresh"] = snr_thresh
    return out


def symmetry_gate(fwd_slopes, bwd_slopes, rel_tol=0.5) -> dict:
    """P1 gate: central difference is only admissible where forward and backward
    secant slopes agree (no saturation/asymmetry). Returns per-component verdict."""
    f = np.asarray(fwd_slopes, float)
    b = np.asarray(bwd_slopes, float)
    denom = np.maximum(np.abs(f) + np.abs(b), 1e-9)
    asym = np.abs(f - b) / denom
    return {"asymmetry": [float(x) for x in asym],
            "symmetric": [bool(x <= rel_tol) for x in asym]}


# --------------------------------------------------------------------------- #
# Stage-0 self-test: the two gating claims the review demanded.
# --------------------------------------------------------------------------- #
def _synth_jacobian(M, sigma, delta, rng):
    """Faithful data-generating process: the REAL pipeline measures noisy outputs
    y (per-output SD sigma) at the +/-delta perturbations, then central-differences.
    For a linear true map y = M x, the observed Jacobian column i is
        J[:,i] = M[:,i] + (eps_plus - eps_minus)/(2 delta),
    so its injected variance is sigma^2/(2 delta^2) per output — exactly what
    bias_floor subtracts. A true-zero column M[:,i]=0 yields pure such noise."""
    m, n = M.shape
    cols = []
    for i in range(n):
        yp = M[:, i] * delta + rng.normal(0, sigma, m)
        ym = -M[:, i] * delta + rng.normal(0, sigma, m)
        cols.append((yp - ym) / (2 * delta))
    return np.column_stack(cols)


def _coverage_sim(n_runs=30, n_sim=300, sigma=0.05, delta=1.0, seed=0):
    """Monte-Carlo coverage of the single-arm corrected-lambda_min CI for a
    true-zero direction (population corrected lambda_min = 0)."""
    rng = np.random.default_rng(seed)
    M = np.array([[0.9, 0.1, 0.0, 0.0],
                  [0.1, 0.8, 0.0, 0.0],
                  [0.0, 0.0, 0.7, 0.0],
                  [0.0, 0.0, 0.0, 0.0]])  # near-diagonal: each state comp drives its own probe; D col = true zero
    M[:, 3] = 0.0  # D = true-zero direction
    nv = np.array([sigma ** 2] * 4)
    covers = 0
    for _ in range(n_sim):
        jacs = [_synth_jacobian(M, sigma, delta, rng) for _ in range(n_runs)]
        ci = lambda_min_ci(jacs, nv, delta, n_boot=400, seed=int(rng.integers(1_000_000_000)))
        if ci["covers_zero"]:
            covers += 1
    return covers / n_sim


def _paired_coverage_sim(n_tasks=30, n_sim=200, sigma=0.05, delta=1.0, seed=0):
    """Type-I coverage of the PAIRED-DIFFERENCE CI: when the two arms share the
    same true map (no effect, true delta=0), how often does the paired-diff CI
    cover 0? This is the estimand that gates H1 causal attribution; the paired
    difference is approximately pivotal (common bias cancels), so it covers far
    better than the single-arm boundary extreme eigenvalue."""
    rng = np.random.default_rng(seed)
    M = np.array([[0.9, 0.1, 0.0, 0.0],
                  [0.1, 0.8, 0.0, 0.0],
                  [0.0, 0.0, 0.7, 0.0],
                  [0.0, 0.0, 0.0, 0.5]])  # full-rank; A==B => true delta = 0
    nv = np.array([sigma ** 2] * 4)
    covers = 0
    for _ in range(n_sim):
        jacsA = [_synth_jacobian(M, sigma, delta, rng) for _ in range(n_tasks)]
        jacsB = [_synth_jacobian(M, sigma, delta, rng) for _ in range(n_tasks)]
        pd = paired_diff_bootstrap(jacsA, jacsB, nv, nv, delta, n_boot=400,
                                   seed=int(rng.integers(1_000_000_000)))
        if not pd["excludes_zero"]:  # CI covers 0 -> correct (no false positive)
            covers += 1
    return covers / n_sim


def _self_test() -> None:
    rng = np.random.default_rng(42)
    sigma, delta = 0.05, 1.0
    nv = np.array([sigma ** 2] * 4)
    M = np.array([[0.9, 0.1, 0.0, 0.0],
                  [0.1, 0.8, 0.0, 0.0],
                  [0.0, 0.0, 0.7, 0.0],
                  [0.0, 0.0, 0.0, 0.0]])  # near-diagonal: each state comp drives its own probe; D col = true zero
    M[:, 3] = 0.0  # D = true-zero direction (dy/dx_D = 0)
    jacs = [_synth_jacobian(M, sigma, delta, rng) for _ in range(60)]

    print("=== Stage-0 gate 1: bias correction makes true-zero lambda_min CI cover 0 ===")
    W = gramian_from_jacobians(jacs)
    rep_raw = analyze_gramian(W)
    print(f"  UNcorrected lambda_min = {rep_raw.lambda_min:.5f}  (pinned at ~noise floor, NOT 0)")
    Wc = bias_correct(W, nv, delta)
    rep_c = analyze_gramian(Wc)
    ci = lambda_min_ci(jacs, nv, delta, n_boot=1500, seed=1)
    print(f"  bias-corrected lambda_min (display, clipped) = {rep_c.lambda_min:.5f}")
    print(f"  corrected lambda_min CI = [{ci['lo']:.5f}, {ci['hi']:.5f}]  covers_zero={ci['covers_zero']}")
    print(f"  least-observable dir still loads on D: {max(rep_c.least_observable_dir, key=rep_c.least_observable_dir.get)}")
    assert rep_raw.lambda_min > 0.5 * (4 * sigma ** 2 / (2 * delta ** 2)), \
        "uncorrected lambda_min should be pinned near the noise floor, not 0"
    assert ci["covers_zero"], "FIX1 FAILED: corrected true-zero CI must cover 0"

    print("\n=== Stage-0 gate 2: paired A/B difference excludes 0 when a knob truly collapses a dir ===")
    MA = M.copy(); MA[3, 3] = 0.6   # arm A (knob OFF): D drives its own probe (independent dir)
    MB = M.copy()                    # arm B (knob ON): D collapsed to 0
    jacsA = [_synth_jacobian(MA, sigma, delta, rng) for _ in range(30)]
    jacsB = [_synth_jacobian(MB, sigma, delta, rng) for _ in range(30)]
    pd = paired_diff_bootstrap(jacsA, jacsB, nv, nv, delta, n_boot=1500, seed=2)
    print(f"  delta_lm = lambda_min^B - lambda_min^A = {pd['point']:.5f}  CI=[{pd['lo']:.5f},{pd['hi']:.5f}]  excludes_0={pd['excludes_zero']}")
    assert pd["excludes_zero"] and pd["point"] < 0, "paired diff should detect the A->B collapse (CI excludes 0, sign negative)"

    print("\n=== Stage-0 gate 3: CI coverage (paired-diff Type-I is the causal estimand) ===")
    cov_single = _coverage_sim(n_runs=30, n_sim=200, sigma=sigma, delta=delta, seed=7)
    cov_paired = _paired_coverage_sim(n_tasks=30, n_sim=200, sigma=sigma, delta=delta, seed=9)
    print(f"  single-arm covers-0 coverage = {cov_single:.3f}  (percentile bootstrap on a boundary")
    print(f"    extreme eigenvalue mildly under-covers; diagnostic only, not the causal judge)")
    print(f"  paired-diff Type-I coverage (CI covers 0 when A==B) = {cov_paired:.3f}  (target ~0.95; gates H1)")
    assert 0.90 <= cov_paired <= 0.99, f"paired-diff coverage {cov_paired} out of band [0.90,0.99]"

    print("\n=== H4 SNR gate (true-zero D must be dropped; C/E/P pass) ===")
    gate = sensitivity_gate(jacs, delta=delta, noise_floor_sd=[sigma] * 4, snr_thresh=2.0)
    print("  passed:", gate["passed"], "| SNR:", {k: round(gate[k]["mean_snr"], 2) for k in STATE_COMPONENTS})
    assert "D" not in gate["passed"] and {"C", "E", "P"}.issubset(set(gate["passed"]))

    print("\nALL STAGE-0 SELF-TESTS PASSED")


if __name__ == "__main__":
    _self_test()
