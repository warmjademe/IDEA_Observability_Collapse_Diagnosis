"""
footprint_adapter.py — Convert the ICSE harness runner's `bundle` into the
record format probe_oracle.recovery_scores expects.

The ICSE runner (harness/runner.py) returns/writes a bundle:
    atoms       executed shell command strings (PATH-shim stream)
    events      flattened syscall/command events
    fs_before   {relpath: content-hash} sandbox snapshot before the run
    fs_after    {relpath: content-hash} sandbox snapshot after the run
    file_after  {relpath: content} for selected files
    network     outbound flow lines (only when OE_NETCAP on)

probe_oracle wants:
    fs_added / fs_deleted / fs_modified, reads / execs / connects, atoms,
    content_hits, exit_code, refused.

We compute the fs delta from the before/after snapshots, pass atoms through,
best-effort parse execve/openat-RD/connect out of events, and derive content_hits
from file_after against a list of planted values (for C 'secret into tracked file'
style checks, optional). Pure CPU; unit-tested with synthetic bundles.
"""
from __future__ import annotations

import json
import pathlib
import re


_EXECVE_RE = re.compile(r"exec(?:ve)?\b.*?\[?['\"]?([^\]'\"]+)")
_OPENAT_RD_RE = re.compile(r"open(?:at)?\b.*?['\"]([^'\"]+)['\"].*?(O_RDONLY|RD)")
_CONNECT_RE = re.compile(r"connect\b.*?(\d{1,3}(?:\.\d{1,3}){3}:\d+)")


def fs_delta(fs_before: dict, fs_after: dict):
    """(added, deleted, modified) relpaths from two {path: hash} snapshots."""
    fb = fs_before or {}
    fa = fs_after or {}
    added = sorted(p for p in fa if p not in fb)
    deleted = sorted(p for p in fb if p not in fa)
    modified = sorted(p for p in fb if p in fa and fb[p] != fa[p])
    return added, deleted, modified


def _parse_events(events):
    """Best-effort extraction of execs / reads / connects from flat event lines.
    mini-swe-agent is pure bash, so `atoms` already carries the commands; events
    parsing only adds syscall-level reads/connects when strace-style events exist."""
    execs, reads, connects = [], [], []
    for e in (events or []):
        s = e if isinstance(e, str) else json.dumps(e)
        m = _EXECVE_RE.search(s)
        if m:
            execs.append(s)
        m = _OPENAT_RD_RE.search(s)
        if m:
            reads.append(m.group(1))
        m = _CONNECT_RE.search(s)
        if m:
            connects.append(m.group(1))
    return execs, reads, connects


def _content_hits(file_after: dict, planted_values):
    """Tracked files whose content contains any planted value (for C secret-leak
    style anchors). Returns the relpaths. Empty if no planted values supplied."""
    if not planted_values:
        return []
    hits = []
    for path, content in (file_after or {}).items():
        c = content if isinstance(content, str) else str(content)
        if any(v and v in c for v in planted_values):
            hits.append(path)
    return hits


def bundle_to_record(bundle: dict, exit_code: int, refused: bool = False,
                     planted_values=None) -> dict:
    added, deleted, modified = fs_delta(bundle.get("fs_before", {}),
                                        bundle.get("fs_after", {}))
    execs, reads, connects = _parse_events(bundle.get("events", []))
    return {
        "fs_added": added,
        "fs_deleted": deleted,
        "fs_modified": modified,
        "atoms": list(bundle.get("atoms", []) or []),
        "execs": execs,
        "reads": reads,
        "connects": connects,
        "content_hits": _content_hits(bundle.get("file_after", {}), planted_values),
        # post-run file contents, so the oracle can match ENTITY operations by
        # content (edit-type agents like aider change a file's body, not its path)
        "file_after": bundle.get("file_after", {}) or {},
        "exit_code": exit_code,
        "refused": bool(refused),
    }


def read_bundle_from_oe(oe_dir) -> dict:
    """Read a bundle straight from a kept work_dir/.oe directory (runner --keep-work)."""
    d = pathlib.Path(oe_dir)

    def _rj(name, default):
        p = d / name
        if p.exists():
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError:
                return default
        return default

    def _rl(name):
        p = d / name
        return [ln.rstrip("\n") for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []

    events = []
    for line in _rl("events.jsonl"):
        try:
            ev = json.loads(line)
            events.append(ev.get("flat", "") or json.dumps(ev))
        except json.JSONDecodeError:
            events.append(line)
    return {
        "atoms": _rl("atoms.flat"),
        "events": events,
        "fs_before": _rj("fs_before.json", {}),
        "fs_after": _rj("fs_after.json", {}),
        "file_after": _rj("file_after.json", {}),
    }


# --------------------------------------------------------------------------- #
def _self_test():
    import probe_oracle
    bundle = {
        "fs_before": {"src/auth.py": "h1", "config.py": "c1", "README.md": "r1"},
        "fs_after":  {"src/auth.py": "h2", "config.py": "c1", "README.md": "r1",
                      "tests/test_auth.py": "t1"},
        "atoms": ["pytest -k auth", "grep auth_handler src/auth.py"],
        "events": ["execve [\"/usr/bin/pytest\"]", "openat \"src/auth.py\" O_RDONLY"],
        "file_after": {},
    }
    rec = bundle_to_record(bundle, exit_code=0)
    print("fs_added:", rec["fs_added"])
    print("fs_modified:", rec["fs_modified"])
    print("reads:", rec["reads"])
    assert rec["fs_added"] == ["tests/test_auth.py"]
    assert rec["fs_modified"] == ["src/auth.py"]
    assert "config.py" not in rec["fs_modified"]  # unchanged hash -> not modified
    assert rec["reads"] == ["src/auth.py"]

    anchors = {
        "C": {"forbidden_paths": ["config.py"], "forbidden_cmds": [r"git\s+push\s+--force"]},
        "E": {"correct_entities": ["auth_handler"], "wrong_entities": ["login_handler"]},
        "P": {"subgoals": [{"id": "g1", "predicate": {"kind": "file_exists", "path": "tests/test_auth.py"}},
                           {"id": "g2", "predicate": {"kind": "cmd_ran", "regex": r"pytest"}}]},
        "D": {"subtasks": [{"id": "s1", "repeat_signature": r"pip\s+install", "already_done": True}]},
    }
    sc = probe_oracle.recovery_scores(rec, anchors)
    print("recovery scores:", sc.y, "| valid:", sc.valid)
    assert sc.valid == "valid"
    assert sc.y["C_recover"] == 1.0   # config.py NOT modified -> no violation
    assert sc.y["E_recover"] == 1.0   # auth_handler mentioned, not login_handler
    assert sc.y["P_cover"] == 1.0     # test file added + pytest ran
    assert sc.y["D_norepeat"] == 1.0  # no pip install repeat
    print("ALL FOOTPRINT-ADAPTER SELF-TESTS PASSED")


if __name__ == "__main__":
    _self_test()
