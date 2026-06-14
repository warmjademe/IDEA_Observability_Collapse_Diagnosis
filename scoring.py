#!/usr/bin/env python3
"""Harness-agnostic scoring: build the (fs_before, fs_after, file_after) bundle from
GROUND TRUTH on disk -- the scenario fixture (initial state) + the kept host sandbox
(final state) -- instead of trusting each harness entrypoint to dump fs snapshots into
.oe. Several CLI agents (cline/goose/pi/qwen) edit files correctly but never write
fs_before/fs_after, which made the oracle falsely report "no-engagement". Reading the
kept work dir fixes that uniformly for every harness.

atoms.flat (command trace from oe_strace) is still read from .oe when present, for the
D (repeated-work) signal."""
import hashlib
import os
import pathlib

import footprint_adapter as fa
import probe_oracle as po

SKIP_DIRS = {".oe", ".git", "__pycache__", ".cline", "node_modules"}


def _h(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()


def _walk(sandbox):
    """Return (fs {rel:hash}, files {rel:content}) for the kept host sandbox."""
    fs, files = {}, {}
    sandbox = pathlib.Path(sandbox)
    if not sandbox.is_dir():
        return fs, files
    for root, dirs, fnames in os.walk(sandbox):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in fnames:
            p = pathlib.Path(root) / fn
            rel = str(p.relative_to(sandbox))
            try:
                content = p.read_text(errors="replace")
            except Exception:
                continue
            files[rel] = content
            fs[rel] = _h(content)
    return fs, files


def _before(scenario):
    """fs_before {rel:hash} + file_before {rel:content} from the scenario fixture."""
    fs, files = {}, {}
    for ent in scenario.get("fixture", []) or []:
        rel = ent.get("path")
        if not rel:
            continue
        content = ent.get("content", "")
        files[rel] = content
        fs[rel] = _h(content)
    return fs, files


def build_bundle(run_dir, scenario):
    """run_dir = work_base/<run-id>; expects <run_dir>/sandbox + optional <run_dir>/.oe/atoms.flat."""
    run_dir = pathlib.Path(run_dir)
    fs_before, _ = _before(scenario)
    fs_after, file_after = _walk(run_dir / "sandbox")
    atoms_p = run_dir / ".oe" / "atoms.flat"
    atoms = ([ln.rstrip("\n") for ln in atoms_p.read_text(errors="replace").splitlines() if ln.strip()]
             if atoms_p.exists() else [])
    return {"atoms": atoms, "events": [], "fs_before": fs_before,
            "fs_after": fs_after, "file_after": file_after}


def score(run_dir, scenario, anchors):
    """Return probe_detail dict for one kept run dir (ground-truth from disk)."""
    bundle = build_bundle(run_dir, scenario)
    rec = fa.bundle_to_record(bundle, 0)
    return po.probe_detail(rec, anchors)
