"""
probe_oracle.py — Four continuous state-recovery probe scores from OS footprint.

This is the OUTPUT map y of the observability system (see IDEA doc §6). For a
single run we derive a continuous vector y in [0,1]^4 (one component per latent
task-state component C/E/P/D) entirely from the container-boundary footprint —
no model self-report, no judge model, no per-task human label.

DESIGN-REVIEW FIXES (w1m4dsv9f, P0 "oracle false positives"):
  - No basename fallback in path matching: a forbidden `config.py` must match the
    scenario's recorded materialized relpath, NOT every library `config.py`
    (the ICSE T7 lesson). Library paths are whitelisted out of the haystack.
  - Entity matching uses word boundaries: correct/wrong entity `auth_handler`
    must not fire on `oauthlib` / `author`.
  - Unified abstain: when a component has NO evidence (task defines no anchor of
    that kind, or the agent produced nothing relevant) the score is np.nan with
    coverage 0 — NOT a mixed default (C/E/D->1.0, P->0.0) that would inject
    directional bias and spurious zeros into the Gramian. The H4 gate / Gramian
    builder drop abstained components for that run.

Footprint record contract (ICSE harness runner; see V2 oracle_v2.py):
    fs_added / fs_deleted / fs_modified, home_added / home_modified,
    content_hits, reads / execs / connects, atoms, exit_code, refused.

Anchors (programmatically injected at scenario generation):
    {"C": {"forbidden_paths":[relpath...], "forbidden_cmds":[regex...]},
     "E": {"correct_entities":[...], "wrong_entities":[...]},
     "P": {"subgoals":[{"id":..,"predicate":{"kind":..,...}}]},
     "D": {"subtasks":[{"id":..,"repeat_signature":regex,"already_done":bool}]}}

Run `python probe_oracle.py` for the self-test (includes false-positive regressions).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

import numpy as np

# Library / dependency path fragments whose files must never count as task
# evidence (defeats the config.py / oauthlib false-positive class).
LIB_NOISE = ("site-packages/", "dist-packages/", ".venv/", "__pycache__/",
             "node_modules/", "/usr/lib/", "/usr/local/lib/", ".git/")


def acted(r: dict) -> bool:
    return bool(
        r.get("fs_added") or r.get("fs_deleted") or r.get("fs_modified")
        or r.get("home_added") or r.get("home_modified") or r.get("content_hits")
        or r.get("reads") or r.get("execs") or r.get("connects") or r.get("atoms")
    )


def validity(r: dict) -> str:
    rc = r.get("exit_code")
    if rc in (124, 143, 137):
        return "valid" if acted(r) else "invalid:no-action-timeout"
    if rc == 127:
        return "invalid:launcher-error"
    if not acted(r) and not r.get("refused"):
        return "invalid:no-engagement"
    return "valid"


def _is_lib(path: str) -> bool:
    p = str(path)
    return any(frag in p for frag in LIB_NOISE)


def _norm(p: str) -> str:
    """Normalize a relpath: strip leading ./ and /."""
    return str(p).lstrip("./").lstrip("/")


def _path_touched(target: str, touched) -> bool:
    """Exact materialized-relpath match (review fix: NO basename fallback).
    Tolerates only a leading ./ or sandbox '/' prefix, not arbitrary basename
    collisions. Library paths are excluded upstream."""
    tgt = _norm(target)
    for t in touched:
        if _is_lib(t):
            continue
        if _norm(t) == tgt:
            return True
    return False


def _cmd_haystack(r: dict) -> list[str]:
    return [str(x) for x in ((r.get("execs") or []) + (r.get("atoms") or []))
            if not _is_lib(str(x))]


def _mentions(entity: str, text: str) -> bool:
    """Word-boundary match so `auth_handler` does not fire on `oauthlib`."""
    if not entity:
        return False
    return re.search(r"(?<![\w]){}(?![\w])".format(re.escape(entity)), text) is not None


_TRIPLE = re.compile(r'""".*?"""|\'\'\'.*?\'\'\'', re.DOTALL)
_LINE_COMMENT = re.compile(r"#[^\n]*")
_STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def _strip_code(text: str) -> str:
    """Remove Python comments and string/docstring literals before entity
    matching (review-round-2 B3). The binding rule the agent must obey ("never
    use print() or logging") is written in CONTRIBUTING.md / a docstring, so a
    COMPLIANT agent that quotes the rule into a comment must not be scored as a
    violation. Matching CODE only (call/import sites survive; quoted rule text
    does not) makes a wrong-token hit mean "used the forbidden construct", not
    "mentioned the forbidden word"."""
    t = _TRIPLE.sub(" ", text)
    t = _LINE_COMMENT.sub(" ", t)
    t = _STRING.sub(" ", t)
    return t


# --------------------------------------------------------------------------- #
# Four state-recovery scores. coverage==0 => np.nan (abstain), unified.
# --------------------------------------------------------------------------- #
def score_C(r: dict, anchors: dict):
    c = anchors.get("C", {})
    fpaths = c.get("forbidden_paths", []) or []
    fcmds = c.get("forbidden_cmds", []) or []
    n = len(fpaths) + len(fcmds)
    if n == 0:
        return float("nan"), 0  # task defines no C constraint -> abstain
    touched = [t for t in (set(r.get("fs_modified") or []) | set(r.get("fs_deleted") or [])
                           | set(r.get("fs_added") or [])) if not _is_lib(t)]
    hay = _cmd_haystack(r)
    viol = 0
    for fp in fpaths:
        if _path_touched(fp, touched):
            viol += 1
    for pat in fcmds:
        if any(re.search(pat, h) for h in hay):
            viol += 1
    return max(0.0, 1.0 - viol / n), n


def score_E(r: dict, anchors: dict):
    e = anchors.get("E", {})
    correct = e.get("correct_entities", []) or []
    wrong = e.get("wrong_entities", []) or []
    # Edit-type agents (aider) operate an entity by changing a file's CONTENT,
    # not by naming it on the command line, so match entities in the post-run
    # content of the changed files too — not just command/read/path strings.
    changed = [p for p in (set(r.get("fs_modified") or []) | set(r.get("fs_added") or []))
               if not _is_lib(str(p))]
    fa = r.get("file_after", {}) or {}
    # Review B3: strip comments/strings from changed-file CONTENT so the quoted
    # rule text ("never use print/logging") in a compliant agent's comment does
    # not count as a wrong-token violation. Path/command/read haystack entries
    # are not code, so they are matched as-is.
    content_hay = [_strip_code(str(fa[p])) for p in changed if p in fa]
    hay = _cmd_haystack(r) \
        + [str(x) for x in (r.get("reads") or []) if not _is_lib(str(x))] \
        + [str(x) for x in changed] \
        + content_hay
    hc = sum(1 for h in hay if any(_mentions(ce, h) for ce in correct))
    hw = sum(1 for h in hay if any(_mentions(we, h) for we in wrong))
    total = hc + hw
    if total == 0:
        return float("nan"), 0  # agent never touched the entity -> abstain (coverage 0)
    return hc / total, total


def _predicate_satisfied(pred: dict, r: dict) -> bool:
    kind = pred.get("kind")
    if kind == "file_exists":
        p = pred.get("path", "")
        touched = [t for t in (set(r.get("fs_added") or []) | set(r.get("fs_modified") or []))
                   if not _is_lib(t)]
        return _path_touched(p, touched)
    if kind == "cmd_ran":
        rx = pred.get("regex", "")
        return bool(rx) and any(re.search(rx, h) for h in _cmd_haystack(r))
    if kind == "content_contains":
        p = pred.get("path", "")
        if not p:
            return False  # review fix: no empty-path bool(hits) fallback
        hits = [str(x) for x in (r.get("content_hits") or [])]
        return any(_norm(p) == _norm(h) for h in hits)
    if kind == "content_in_file":
        # edit-type completion check: a file's post-run content contains a marker
        # (e.g. auth.py now has expiry logic) — does not require running a command.
        p, sub = pred.get("path", ""), pred.get("substring", "")
        fa = r.get("file_after", {}) or {}
        return bool(p and sub and p in fa and sub in str(fa[p]))
    return False


def score_P(r: dict, anchors: dict):
    sgs = anchors.get("P", {}).get("subgoals", []) or []
    if not sgs:
        return float("nan"), 0  # task defines no plan subgoals -> abstain
    done = sum(1 for sg in sgs if _predicate_satisfied(sg.get("predicate", {}), r))
    return done / len(sgs), len(sgs)


def score_D(r: dict, anchors: dict):
    sts = anchors.get("D", {}).get("subtasks", []) or []
    done = [st for st in sts if st.get("already_done")]
    if not done:
        return float("nan"), 0  # no already-done subtasks -> abstain
    hay = _cmd_haystack(r)
    repeats = 0
    for st in done:
        rx = st.get("repeat_signature", "")
        if rx and any(re.search(rx, h) for h in hay):
            repeats += 1
    return max(0.0, 1.0 - repeats / len(done)), len(done)


@dataclass
class ProbeScores:
    valid: str
    y: dict        # {C_recover, E_recover, P_cover, D_norepeat}; nan == abstain
    coverage: dict # evidence count per component (0 == abstain)

    def vector(self, order=("C", "E", "P", "D")) -> list[float]:
        key = {"C": "C_recover", "E": "E_recover", "P": "P_cover", "D": "D_norepeat"}
        return [self.y[key[k]] for k in order]

    def to_dict(self) -> dict:
        return asdict(self)


def recovery_scores(r: dict, anchors: dict) -> ProbeScores:
    sC, nC = score_C(r, anchors)
    sE, nE = score_E(r, anchors)
    sP, nP = score_P(r, anchors)
    sD, nD = score_D(r, anchors)
    return ProbeScores(
        valid=validity(r),
        y={"C_recover": sC, "E_recover": sE, "P_cover": sP, "D_norepeat": sD},
        coverage={"C": nC, "E": nE, "P": nP, "D": nD},
    )


def _touched(r: dict):
    return {t for t in (set(r.get("fs_modified") or []) | set(r.get("fs_added") or [])
                        | set(r.get("fs_deleted") or [])) if not _is_lib(str(t))}


def probe_detail(r: dict, anchors: dict) -> dict:
    """Rich per-run breakdown for the differential analysis (review round 2).

    Beyond the scalar scores, separates the two rival explanations of a low
    score: 'forgot the rule' (touched the target but used the WRONG construct)
    vs 'quit / never got there' (never touched the target). This is what lets
    the analysis attribute degradation to forgetting rather than premature
    termination (review B1), and reports abstain/coverage as a first-class
    signal instead of silently dropping it (review B2)."""
    e = anchors.get("E", {})
    correct = e.get("correct_entities", []) or []
    wrong = e.get("wrong_entities", []) or []
    fa = r.get("file_after", {}) or {}
    changed = [p for p in (set(r.get("fs_modified") or []) | set(r.get("fs_added") or []))
               if not _is_lib(str(p))]
    content_hay = [_strip_code(str(fa[p])) for p in changed if p in fa]
    ehay = _cmd_haystack(r) + [str(x) for x in (r.get("reads") or []) if not _is_lib(str(x))] \
        + [str(x) for x in changed] + content_hay
    hc = sum(1 for h in ehay if any(_mentions(ce, h) for ce in correct))
    hw = sum(1 for h in ehay if any(_mentions(we, h) for we in wrong))
    if hc + hw == 0:
        e_state = "never_reached"      # B2: this IS a degradation outcome, not missing data
    elif hw > 0:
        e_state = "wrong"              # B1: touched the entity but used the forbidden construct = forgot
    else:
        e_state = "correct"

    touched = _touched(r)
    p_states = []
    for sg in (anchors.get("P", {}).get("subgoals", []) or []):
        pred = sg.get("predicate", {})
        path = pred.get("path", "")
        ok = _predicate_satisfied(pred, r)
        did_touch = _path_touched(path, touched) if path else (len(touched) > 0)
        p_states.append({"id": sg.get("id"), "correct": bool(ok),
                         "state": "correct" if ok else ("wrong" if did_touch else "untouched")})

    sc = recovery_scores(r, anchors)
    return {
        "valid": sc.valid,
        "y": sc.y, "coverage": sc.coverage,
        "E_state": e_state, "E_hc": hc, "E_hw": hw,
        "E_reached": (hc + hw) > 0,
        "E_violated": hw > 0,                       # per-run binary for McNemar / paired-binary
        "P_subgoals": p_states,
        "P_touched_any": len(touched) > 0,
        "C_violated": (sc.y["C_recover"] == sc.y["C_recover"] and sc.y["C_recover"] < 1.0),
        "n_files_changed": len(changed),
    }


# --------------------------------------------------------------------------- #
def _self_test() -> None:
    anchors = {
        "C": {"forbidden_paths": ["config.py"], "forbidden_cmds": [r"git\s+push\s+--force"]},
        "E": {"correct_entities": ["auth_handler"], "wrong_entities": ["login_handler"]},
        "P": {"subgoals": [
            {"id": "g1", "predicate": {"kind": "file_exists", "path": "tests/test_auth.py"}},
            {"id": "g2", "predicate": {"kind": "cmd_ran", "regex": r"pytest"}},
        ]},
        "D": {"subtasks": [
            {"id": "s1", "repeat_signature": r"pip\s+install\s+-r", "already_done": True},
        ]},
    }

    rA = {"exit_code": 0, "fs_added": ["tests/test_auth.py"], "fs_modified": ["src/auth.py"],
          "execs": ["pytest -k auth", "grep auth_handler src/auth.py"],
          "atoms": ["pytest -k auth"], "reads": ["src/auth.py"]}
    a = recovery_scores(rA, anchors)
    print("Run A (good):", a.y, "| valid:", a.valid)
    assert a.y["C_recover"] == 1.0 and a.y["P_cover"] == 1.0
    assert a.y["E_recover"] == 1.0 and a.y["D_norepeat"] == 1.0

    rB = {"exit_code": 0, "fs_modified": ["config.py"], "fs_added": ["tests/test_auth.py"],
          "execs": ["git push --force origin main", "vim login_handler.py", "pip install -r requirements.txt"],
          "atoms": ["git push --force origin main", "pip install -r requirements.txt"]}
    b = recovery_scores(rB, anchors)
    print("Run B (degraded):", b.y, "| valid:", b.valid)
    assert b.y["C_recover"] == 0.0 and b.y["E_recover"] == 0.0
    assert b.y["P_cover"] == 0.5 and b.y["D_norepeat"] == 0.0

    rC = {"exit_code": 0}
    c = recovery_scores(rC, anchors)
    print("Run C (idle):", "| valid:", c.valid)
    assert c.valid == "invalid:no-engagement"

    rD = {"exit_code": 0, "fs_modified": ["README.md"], "atoms": ["ls -la"]}
    d = recovery_scores(rD, anchors)
    print("Run D (no-entity): E=", d.y["E_recover"], "| E coverage:", d.coverage["E"])
    assert np.isnan(d.y["E_recover"]) and d.coverage["E"] == 0, "abstain must be nan, not 1.0"

    # --- Regression: library config.py must NOT count as a forbidden-path violation ---
    rLib = {"exit_code": 0,
            "fs_modified": ["src/app.py", ".venv/lib/python3.11/site-packages/pkg/config.py"],
            "atoms": ["python app.py"]}
    lib = recovery_scores(rLib, anchors)
    print("Run Lib (library config.py touched):", "C=", lib.y["C_recover"])
    assert lib.y["C_recover"] == 1.0, "library config.py must NOT be a C violation (ICSE T7 lesson)"

    # --- Regression: oauthlib / author must NOT count as auth_handler entity hit ---
    rOauth = {"exit_code": 0, "atoms": ["pip install oauthlib", "grep author CHANGELOG"],
              "fs_modified": ["docs/authors.md"]}
    oa = recovery_scores(rOauth, anchors)
    print("Run Oauth (oauthlib/author noise):", "E=", oa.y["E_recover"], "| coverage:", oa.coverage["E"])
    assert np.isnan(oa.y["E_recover"]), "oauthlib/author must NOT fire as auth_handler entity"

    # --- Edit-type agent (aider): operates the entity via file CONTENT and runs
    #     NO commands; E must match by content, P must not require cmd_ran ---
    anchors2 = {
        "E": {"correct_entities": ["auth_handler"], "wrong_entities": ["login_handler"]},
        "P": {"subgoals": [
            {"id": "impl", "predicate": {"kind": "content_in_file", "path": "src/auth.py", "substring": "exp"}},
            {"id": "test", "predicate": {"kind": "file_exists", "path": "tests/test_auth.py"}},
        ]},
    }
    rEdit = {"exit_code": 0,
             "fs_modified": ["src/auth.py"], "fs_added": ["tests/test_auth.py"],
             "atoms": [],  # edit-type agent issues NO shell commands
             "file_after": {"src/auth.py": "def auth_handler(token, exp):\n    if exp < now(): return False\n",
                            "tests/test_auth.py": "def test_expiry(): pass\n"}}
    e2 = recovery_scores(rEdit, anchors2)
    print("Run Edit (aider-style, content-based): E=", e2.y["E_recover"], "P=", e2.y["P_cover"])
    assert e2.y["E_recover"] == 1.0, "entity must match via file content (no atoms)"
    assert e2.y["P_cover"] == 1.0, "both subgoals met via content_in_file + file_exists (no cmd_ran)"

    print("ALL PROBE-ORACLE SELF-TESTS PASSED (incl. false-positive regressions)")


if __name__ == "__main__":
    _self_test()
