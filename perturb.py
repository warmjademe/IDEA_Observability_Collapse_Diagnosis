"""
perturb.py — Controlled presentation-strength perturbation of state anchors.

REVISED after design review (w1m4dsv9f, P0-2). The earlier "injection strength"
perturbation deleted the sole statement of a component at the low end, which (a)
changed the task itself (a deletion makes "violating the constraint" the correct
behavior — measuring task difficulty, not harness transmission) and (b) saturated
at the high end (a perfectly transmitted constraint reads as dy/dx≈0, the wrong
sign). Both are construct-validity failures.

The fix: the anchor's SEMANTIC CONTENT is fixed and the agent is ALWAYS told it
at least once. The perturbation only varies the PRESENTATION REDUNDANCY (how many
times / at what context depth the anchor is restated upstream of the harness), so
that what we vary is how much redundancy the harness's context operator has to
work with — not whether the task contains the information. With base>=3 the whole
ladder {base-2,...,base+2} keeps s>=1, so every arm still states the anchor.

Sensitivity is then read with BOTH one-sided secants (forward/backward); the
symmetry gate in gramian.py refuses the central difference where they disagree
(saturation/asymmetry), instead of silently averaging 0.05 and 0.75 into 0.40.

A scenario:
    {
      "id": str,
      "task_body": str,                      # semantic task (FIXED, never perturbed)
      "fixture": [{"path","content"}],       # files materialized into the sandbox
      "state_anchors": {
        "C"|"E"|"P"|"D": {
           "statement": str,                 # natural-language anchor (FIXED content)
           "base": int (>=3),                # base presentation strength
           "oracle_anchor": {...}            # passed through to probe_oracle (FIXED)
        }, ...
      },
      "user_prompt": str                      # rendered product (set by render_prompt)
    }

Run `python perturb.py` for the self-test.
"""
from __future__ import annotations

import copy

STATE_COMPONENTS = ("C", "E", "P", "D")
DEFAULT_BASE = 3
DEFAULT_DELTAS = (-2, -1, 0, 1, 2)


def render_prompt(scen: dict, strengths: dict) -> str:
    """Render user_prompt by restating each component's anchor `s_i` times
    (s_i >= 1 enforced), followed by the fixed task body. Restatements are placed
    at the TOP (shallow depth) so a harness that truncates/compresses early context
    is what determines whether the restatements survive — the manipulated variable
    lives on the harness link, not in task semantics."""
    anchors = scen.get("state_anchors", {})
    blocks: list[str] = []
    for comp in STATE_COMPONENTS:
        if comp not in anchors:
            continue
        s = max(1, int(strengths.get(comp, anchors[comp].get("base", DEFAULT_BASE))))
        stmt = anchors[comp]["statement"].strip()
        for _ in range(s):
            blocks.append(stmt)
    header = "\n".join(blocks)
    body = scen["task_body"].strip()
    return (header + "\n\n" + body) if header else body


def base_strengths(scen: dict) -> dict:
    return {c: int(scen["state_anchors"][c].get("base", DEFAULT_BASE))
            for c in scen.get("state_anchors", {})}


def perturb_scenario(scen: dict, component: str, s_value: int) -> dict:
    """Return a scenario copy with `component` presented at strength s_value and
    all others at their base. Semantic content (task_body, statements,
    oracle_anchor) is byte-identical across the ladder; only the restatement
    count of `component` changes."""
    if component not in scen.get("state_anchors", {}):
        raise ValueError(f"scenario has no state anchor for {component!r}")
    if s_value < 1:
        raise ValueError("s_value must be >= 1 (anchor must always be told once)")
    strengths = base_strengths(scen)
    strengths[component] = int(s_value)
    new = copy.deepcopy(scen)
    new["user_prompt"] = render_prompt(scen, strengths)
    new["_perturb"] = {"component": component, "s": int(s_value), "strengths": strengths}
    return new


def delta_ladder(base: int = DEFAULT_BASE, deltas=DEFAULT_DELTAS) -> list[int]:
    """The s-values for the ±delta ladder, clamped to s>=1. base>=3 keeps the full
    {-2..+2} ladder strictly positive (anchor always told)."""
    if base < 3:
        raise ValueError("base must be >= 3 so the +/-2 ladder stays s>=1")
    return [max(1, base + d) for d in deltas]


def ladder_scenarios(scen: dict, component: str, deltas=DEFAULT_DELTAS) -> list[dict]:
    """All perturbed scenarios for one component's ladder (for one-sided + central
    differences). Each carries _perturb.s so the runner/oracle can index them."""
    base = scen["state_anchors"][component].get("base", DEFAULT_BASE)
    return [perturb_scenario(scen, component, s) for s in delta_ladder(base, deltas)]


def oracle_anchors(scen: dict) -> dict:
    """Assemble the anchors dict that probe_oracle.recovery_scores expects, from
    each component's fixed oracle_anchor (never perturbed)."""
    out = {}
    for comp, a in scen.get("state_anchors", {}).items():
        if "oracle_anchor" in a:
            out[comp] = a["oracle_anchor"]
    return out


# --------------------------------------------------------------------------- #
def _self_test() -> None:
    scen = {
        "id": "demo_long_task",
        "task_body": "Refactor the authentication module and add tests.",
        "fixture": [{"path": "src/auth.py", "content": "# auth\n"}],
        "state_anchors": {
            "C": {"statement": "Do not modify config.py.", "base": 3,
                  "oracle_anchor": {"forbidden_paths": ["config.py"], "forbidden_cmds": []}},
            "E": {"statement": "The handler to edit is named auth_handler.", "base": 3,
                  "oracle_anchor": {"correct_entities": ["auth_handler"], "wrong_entities": ["login_handler"]}},
            "D": {"statement": "Dependencies are already installed; do not reinstall.", "base": 3,
                  "oracle_anchor": {"subtasks": [{"id": "s1", "repeat_signature": r"pip\s+install", "already_done": True}]}},
        },
    }

    # Ladder for E: base=3 -> {1,2,3,4,5}, all >=1 (anchor always told).
    ladder = delta_ladder(base=3)
    print("E ladder s-values:", ladder)
    assert ladder == [1, 2, 3, 4, 5] and min(ladder) >= 1

    scen_lo = perturb_scenario(scen, "E", 1)   # base-2
    scen_hi = perturb_scenario(scen, "E", 5)   # base+2
    n_lo = scen_lo["user_prompt"].count("auth_handler")
    n_hi = scen_hi["user_prompt"].count("auth_handler")
    print(f"E restatements: s=1 -> {n_lo} mention(s); s=5 -> {n_hi} mention(s)")
    assert n_lo == 1 and n_hi == 5, "presentation redundancy must scale with s, min 1"

    # Semantic invariants: task body and the FIXED oracle anchors never change.
    assert scen_lo["task_body"] == scen_hi["task_body"] == scen["task_body"]
    assert oracle_anchors(scen_lo) == oracle_anchors(scen_hi) == oracle_anchors(scen)
    # Other components stay at base across an E-perturbation.
    assert scen_lo["_perturb"]["strengths"]["C"] == 3
    assert scen_lo["user_prompt"].count("config.py") == 3

    # The anchor is ALWAYS present even at the lowest rung (no deletion).
    for s in ladder:
        sp = perturb_scenario(scen, "E", s)
        assert "auth_handler" in sp["user_prompt"], "anchor must never be deleted"

    # ladder_scenarios convenience
    ls = ladder_scenarios(scen, "D")
    assert len(ls) == 5 and [x["_perturb"]["s"] for x in ls] == [1, 2, 3, 4, 5]

    print("oracle_anchors keys:", sorted(oracle_anchors(scen).keys()))
    print("ALL PERTURB SELF-TESTS PASSED")


if __name__ == "__main__":
    _self_test()
