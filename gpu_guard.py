"""
gpu_guard.py — Shared-NAS resource gate for the Observability-Collapse campaign.

The NAS is a multi-project machine. Rule (from the user): if the GPU is busy,
WAIT; only run when the GPU is idle AND CPU load is not high. ollama keeps a
model resident in VRAM as a baseline, so "idle" cannot mean "zero VRAM" — it
means no one is actively computing on the GPU. We therefore gate on GPU
*utilization* sampled repeatedly (a single 0% reading can be a between-request
gap of someone else's collection job), plus CPU load average per core.

Usage:
    python gpu_guard.py --check               # print status, exit 0 if free else 3
    python gpu_guard.py --wait                # block until free (then exit 0)
    python gpu_guard.py --wait --timeout 7200 # give up after 2h (exit 4)

As a library:
    from gpu_guard import wait_until_free, snapshot
    wait_until_free()        # call at the top of any NAS batch before heavy work
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict


@dataclass
class ResourceSnapshot:
    gpu_util_pct: float          # max utilization across GPUs
    gpu_mem_used_mib: float
    gpu_mem_total_mib: float
    gpu_mem_free_mib: float
    loadavg_1m: float
    ncpu: int
    load_per_core: float

    def to_dict(self) -> dict:
        return asdict(self)


def _nvidia_smi_query() -> list[tuple[float, float, float]]:
    """Return [(util%, mem_used_MiB, mem_total_MiB), ...] per GPU."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        raise RuntimeError("nvidia-smi not found")
    out = subprocess.check_output(
        [exe, "--query-gpu=utilization.gpu,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        text=True, timeout=20,
    )
    rows = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
    if not rows:
        raise RuntimeError("nvidia-smi returned no GPU rows")
    return rows


def _loadavg() -> tuple[float, int]:
    with open("/proc/loadavg") as fh:
        la1 = float(fh.read().split()[0])
    try:
        import os
        ncpu = os.cpu_count() or 1
    except Exception:
        ncpu = 1
    return la1, ncpu


def snapshot() -> ResourceSnapshot:
    gpus = _nvidia_smi_query()
    util = max(g[0] for g in gpus)
    # report the GPU we'd most likely land on: the one with most free memory
    mem_used, mem_total = max(gpus, key=lambda g: g[2] - g[1])[1:3]
    la1, ncpu = _loadavg()
    return ResourceSnapshot(
        gpu_util_pct=util,
        gpu_mem_used_mib=mem_used,
        gpu_mem_total_mib=mem_total,
        gpu_mem_free_mib=mem_total - mem_used,
        loadavg_1m=la1,
        ncpu=ncpu,
        load_per_core=la1 / max(ncpu, 1),
    )


def is_free(
    *,
    gpu_util_thresh: float = 25.0,     # %; above this someone is computing
    min_gpu_free_mib: float = 4000.0,  # need headroom for our own inference
    cpu_load_thresh: float = 0.85,     # loadavg_1m / ncpu
    samples: int = 5,
    sample_interval: float = 4.0,
    verbose: bool = False,
) -> tuple[bool, ResourceSnapshot, str]:
    """Free iff GPU utilization stays below threshold across ALL samples
    (defeats between-request dips), enough VRAM is free, and CPU load/core is low.
    Returns (free, last_snapshot, reason)."""
    last = None
    util_readings = []
    for k in range(max(samples, 1)):
        last = snapshot()
        util_readings.append(last.gpu_util_pct)
        if verbose:
            print(f"  sample {k+1}/{samples}: gpu_util={last.gpu_util_pct:.0f}% "
                  f"free={last.gpu_mem_free_mib:.0f}MiB load/core={last.load_per_core:.2f}",
                  flush=True)
        if k < samples - 1:
            time.sleep(sample_interval)
    max_util = max(util_readings)
    if max_util >= gpu_util_thresh:
        return False, last, f"gpu busy (max util {max_util:.0f}% >= {gpu_util_thresh:.0f}% over {samples} samples)"
    if last.gpu_mem_free_mib < min_gpu_free_mib:
        return False, last, f"insufficient VRAM ({last.gpu_mem_free_mib:.0f} < {min_gpu_free_mib:.0f} MiB free)"
    if last.load_per_core >= cpu_load_thresh:
        return False, last, f"cpu busy (load/core {last.load_per_core:.2f} >= {cpu_load_thresh:.2f})"
    return True, last, "free"


def wait_until_free(
    *,
    poll_interval: float = 120.0,
    timeout: float | None = None,
    verbose: bool = True,
    **free_kwargs,
) -> bool:
    """Block until resources are free. Returns True when free, False on timeout."""
    start = time.monotonic()
    while True:
        free, snap, reason = is_free(verbose=verbose, **free_kwargs)
        if free:
            if verbose:
                print(f"[gpu_guard] FREE — proceeding (free={snap.gpu_mem_free_mib:.0f}MiB "
                      f"load/core={snap.load_per_core:.2f})", flush=True)
            return True
        if timeout is not None and (time.monotonic() - start) >= timeout:
            if verbose:
                print(f"[gpu_guard] TIMEOUT after {timeout:.0f}s — last reason: {reason}", flush=True)
            return False
        if verbose:
            print(f"[gpu_guard] waiting: {reason}; re-check in {poll_interval:.0f}s", flush=True)
        time.sleep(poll_interval)


def main() -> int:
    ap = argparse.ArgumentParser(description="Shared-NAS GPU/CPU gate")
    ap.add_argument("--check", action="store_true", help="print status once, exit 0 if free else 3")
    ap.add_argument("--wait", action="store_true", help="block until free")
    ap.add_argument("--timeout", type=float, default=None, help="seconds before giving up (with --wait)")
    ap.add_argument("--gpu-util-thresh", type=float, default=25.0)
    ap.add_argument("--min-gpu-free-mib", type=float, default=4000.0)
    ap.add_argument("--cpu-load-thresh", type=float, default=0.85)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--poll-interval", type=float, default=120.0)
    args = ap.parse_args()

    kw = dict(
        gpu_util_thresh=args.gpu_util_thresh,
        min_gpu_free_mib=args.min_gpu_free_mib,
        cpu_load_thresh=args.cpu_load_thresh,
        samples=args.samples,
    )
    if args.wait:
        ok = wait_until_free(poll_interval=args.poll_interval, timeout=args.timeout, **kw)
        return 0 if ok else 4
    # default: --check
    free, snap, reason = is_free(verbose=True, **kw)
    import json
    print(json.dumps({"free": free, "reason": reason, **snap.to_dict()}, indent=2))
    return 0 if free else 3


if __name__ == "__main__":
    sys.exit(main())
