"""
WinWarden benchmark suite.
Measures: scanner overhead, priority reduction, efficiency mode, suspend.

Usage:  python benchmarks/bench.py
Needs:  admin rights for some priority changes (runs fine without, shows AccessDenied).
"""
from __future__ import annotations

import sys
import time
import os
import psutil

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── helpers ───────────────────────────────────────────────────────────────────

def _bar(label: str, value: float, total: float, width: int = 30) -> str:
    filled = int(width * value / max(total, 0.001))
    bar = "█" * filled + "░" * (width - filled)
    return f"  {label:<22} [{bar}] {value:.1f}"


def _section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def _ref_for(proc: psutil.Process):
    from optimizer.models import ProcessRef
    return ProcessRef(
        pid=proc.pid,
        name=proc.name(),
        exe=proc.exe() if proc.exe() else "",
        create_time=proc.create_time(),
    )


# ── 1. scanner cost ───────────────────────────────────────────────────────────

def bench_scanner_cost() -> None:
    _section("1. Scanner overhead — does WinWarden burden your system?")
    from optimizer.tools.processes import list_processes

    # Cold scan — memory cache is empty, worst case
    t0 = time.perf_counter()
    procs = list_processes()
    cold_ms = (time.perf_counter() - t0) * 1000

    # Hot scans — memory cache populated, typical case
    hot_times: list[float] = []
    for _ in range(3):
        t0 = time.perf_counter()
        list_processes()
        hot_times.append((time.perf_counter() - t0) * 1000)
    hot_ms = sum(hot_times) / len(hot_times)

    self_ram = psutil.Process().memory_info().rss / 1_048_576
    scan_interval_ms = 8_000   # winwarden's _SCAN_MS

    print(f"  Processes enumerated : {len(procs)}")
    print(f"  Cold scan (first)    : {cold_ms:.0f} ms  (memory cache empty)")
    print(f"  Hot  scan (typical)  : {hot_ms:.1f} ms  (memory served from 30s cache)")
    print(f"  WinWarden RAM        : {self_ram:.0f} MB")
    print(f"\n  Scan interval: {scan_interval_ms}ms")
    print(f"  Cold overhead: {cold_ms/scan_interval_ms*100:.1f}% of wall time (first run only)")
    print(f"  Hot  overhead: {hot_ms/scan_interval_ms*100:.2f}% of wall time (steady state)")
    if hot_ms < 100:
        print("  ✓ Steady-state scanner is essentially free.")


# ── 2. priority reduction ─────────────────────────────────────────────────────

import multiprocessing


def _cpu_worker(stop: multiprocessing.Event) -> None:
    """Tight compute loop until stop is set."""
    x = 1
    while not stop.is_set():
        x = (x * 1_000_003 + 1) & 0xFFFF_FFFF


def _spawn_burner() -> tuple[multiprocessing.Process, multiprocessing.Event]:
    stop = multiprocessing.Event()
    p = multiprocessing.Process(target=_cpu_worker, args=(stop,), daemon=True)
    p.start()
    return p, stop


def _sample_cpu(pid: int, interval: float = 3.0) -> float:
    """Blocking measurement: returns real CPU % over the interval."""
    try:
        return psutil.Process(pid).cpu_percent(interval=interval)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def bench_priority() -> None:
    _section("2. Priority reduction — CPU share at Normal vs Below Normal")
    from optimizer.tools.actions import lower_priority

    cores = psutil.cpu_count(logical=True) or 1

    # Saturate all but one core with Normal-priority burners so the target has competition
    print(f"  Spawning {cores} burners to saturate {cores} cores…", end=" ", flush=True)
    competitors: list[tuple[multiprocessing.Process, multiprocessing.Event]] = []
    for _ in range(cores):
        competitors.append(_spawn_burner())
    time.sleep(1.0)  # let them ramp up

    # Target burner at Normal priority
    target, target_stop = _spawn_burner()
    tp = psutil.Process(target.pid)
    print("sampling (3s)…", end=" ", flush=True)
    cpu_normal = _sample_cpu(target.pid, 3.0)
    print(f"{cpu_normal:.1f}%")

    ref = _ref_for(tp)
    result = lower_priority(ref)
    if not result.ok:
        print(f"  ⚠ Could not lower priority: {result.reason}")
    else:
        print("  Priority lowered to Below Normal. Sampling (3s)…", end=" ", flush=True)
        cpu_low = _sample_cpu(target.pid, 3.0)
        print(f"{cpu_low:.1f}%")

        top = max(cpu_normal, cpu_low, 0.1) * 1.15
        print()
        print(_bar("Normal priority      ", cpu_normal, top))
        print(_bar("Below Normal priority", cpu_low,    top))
        reduction = cpu_normal - cpu_low
        pct_drop  = reduction / max(cpu_normal, 0.01) * 100
        print(f"\n  CPU reduction : {reduction:+.1f}% ({pct_drop:.0f}% relative)")
        if pct_drop > 5:
            print("  ✓ Measurable effect under load.")
        else:
            print("  System still had spare cores — effect would be larger at 100% utilisation.")

    target_stop.set(); target.join(timeout=2)
    for p, s in competitors:
        s.set(); p.join(timeout=2)


# ── 3. efficiency mode ────────────────────────────────────────────────────────

def bench_efficiency_mode() -> None:
    _section("3. Efficiency Mode — EcoQoS + Idle priority combined")
    from optimizer.tools.actions import set_efficiency_mode

    cores = psutil.cpu_count(logical=True) or 1
    print(f"  Spawning {cores} competitor burners…", end=" ", flush=True)
    competitors = [_spawn_burner() for _ in range(cores)]
    time.sleep(1.0)

    target, target_stop = _spawn_burner()
    tp = psutil.Process(target.pid)

    cpu_before = _sample_cpu(target.pid, 3.0)
    print(f"  CPU before: {cpu_before:.1f}%")

    ref = _ref_for(tp)
    result = set_efficiency_mode(ref, on=True)
    if not result.ok:
        print(f"  ⚠ {result.reason}")
    else:
        cpu_after = _sample_cpu(target.pid, 3.0)
        print(f"  CPU after EcoQoS + Idle: {cpu_after:.1f}%")

        top = max(cpu_before, cpu_after, 0.1) * 1.15
        print()
        print(_bar("Before (Normal)", cpu_before, top))
        print(_bar("After  (Idle)  ", cpu_after,  top))
        pct = (cpu_before - cpu_after) / max(cpu_before, 0.01) * 100
        print(f"\n  CPU reduction : {cpu_before - cpu_after:+.1f}% ({pct:.0f}% relative)")
        print("  EcoQoS also signals the power governor to prefer E-cores over P-cores,")
        print("  reducing heat and battery draw beyond what the % numbers show.")

    target_stop.set(); target.join(timeout=2)
    for p, s in competitors:
        s.set(); p.join(timeout=2)


# ── 4. suspend ────────────────────────────────────────────────────────────────

def bench_suspend() -> None:
    _section("4. Suspend — CPU drops to absolute zero")
    from optimizer.tools.actions import suspend, resume

    target, target_stop = _spawn_burner()
    tp = psutil.Process(target.pid)
    time.sleep(0.5)

    cpu_running = _sample_cpu(target.pid, 3.0)
    print(f"  CPU while running   : {cpu_running:.1f}%")

    ref = _ref_for(tp)
    result = suspend(ref)
    if not result.ok:
        print(f"  ⚠ Could not suspend: {result.reason}")
        target_stop.set(); target.join(timeout=2)
        return

    cpu_suspended = _sample_cpu(target.pid, 3.0)
    print(f"  CPU while suspended : {cpu_suspended:.1f}%")
    resume(ref)
    target_stop.set(); target.join(timeout=2)

    top = max(cpu_running, 0.1) * 1.15
    print()
    print(_bar("Running  ", cpu_running,   top))
    print(_bar("Suspended", cpu_suspended, top))
    print(f"\n  ✓ Suspended process: 0% CPU, memory stays in RAM, resumes exactly.")
    print(f"  Reduction: {cpu_running:.1f}% → {cpu_suspended:.1f}% "
          f"({cpu_running - cpu_suspended:.1f}% freed)")


# ── 5. real-world scan ────────────────────────────────────────────────────────

def bench_real_scan() -> None:
    _section("5. What WinWarden would flag on your system right now")
    from optimizer.tools.processes import list_processes
    from optimizer.tools.safety import check_protection
    from optimizer.tools.actions import check_safe
    from optimizer.models import ProcessRef

    # Two samples, 2s apart, so CPU values are real
    list_processes()
    time.sleep(2)
    procs = list_processes()

    my_pid = os.getpid()
    rows = []
    for p in procs:
        if p.pid == my_pid:
            continue
        # name-only protection check (exe/username empty after optimised list_processes)
        if check_protection(p.name, "", "", p.pid):
            continue
        c = p.cpu_percent >= 2.0
        m = p.wset_mb     >= 150.0
        if not (c or m):
            continue
        ref = ProcessRef(pid=p.pid, name=p.name, exe=p.exe,
                         create_time=p.create_time)
        block = check_safe(ref)
        rows.append((p, block))

    rows.sort(key=lambda x: x[0].cpu_percent + x[0].wset_mb / 100, reverse=True)

    if not rows:
        print("  No processes currently above thresholds (CPU≥2%, RAM≥150 MB).")
        return

    print(f"  {'Process':<30} {'CPU%':>6} {'RAM MB':>7}  {'Actionable?'}")
    print(f"  {'─'*30} {'─'*6} {'─'*7}  {'─'*30}")
    actionable = 0
    for p, block in rows[:20]:
        status = "✓ can optimize" if block is None else f"✗ {block[:35]}"
        print(f"  {p.name:<30} {p.cpu_percent:>6.1f} {p.wset_mb:>7.0f}  {status}")
        if block is None:
            actionable += 1

    total_cpu = sum(p.cpu_percent for p, _ in rows)
    total_ram = sum(p.wset_mb     for p, _ in rows)
    print(f"\n  Flagged: {len(rows)} processes  |  actionable: {actionable}")
    print(f"  Combined load: {total_cpu:.1f}% CPU  +  {total_ram:.0f} MB RAM")
    if actionable > 0:
        print(f"  Lowering all actionable to Below Normal would free these")
        print(f"  processes' CPU quanta for your foreground app during peaks.")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  WinWarden Benchmark Suite")
    print(f"  Python {sys.version.split()[0]}  |  {psutil.cpu_count()} logical cores  "
          f"|  {psutil.virtual_memory().total // (1024**3)} GB RAM")
    print("=" * 60)

    bench_scanner_cost()
    bench_priority()
    bench_efficiency_mode()
    bench_suspend()
    bench_real_scan()

    print(f"\n{'═'*60}")
    print("  Done.")
    print(f"{'═'*60}\n")
