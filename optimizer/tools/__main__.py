"""
python -m optimizer.tools <command>

Commands:
  pressure          Print whole-PC stress metrics.
  top [--by cpu|mem] [-n N]
                    List top N processes sorted by CPU or private memory.
  inspect <pid>     Show detailed info for one process.
  act <pid> <action> [--dry-run]
                    Apply an action. Actions: lower, efficiency, suspend, close, terminate.
"""
from __future__ import annotations

import argparse
import sys
import time


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_pressure(_args: argparse.Namespace) -> None:
    from optimizer.tools.system import get_system_pressure
    sp = get_system_pressure()
    print(f"CPU:         {sp.cpu_percent:.1f}%")
    print(f"RAM:         {sp.ram_percent:.1f}%")
    if sp.commit_ratio is not None:
        print(f"Commit:      {sp.commit_ratio:.2f}x  (>0.8 = pressure)")
    if sp.hard_faults_per_s is not None:
        print(f"Hard faults: {sp.hard_faults_per_s:.1f}/s")
    if sp.disk_busy_percent is not None:
        print(f"Disk busy:   {sp.disk_busy_percent:.1f}%")


def cmd_top(args: argparse.Namespace) -> None:
    from optimizer.tools.processes import list_processes
    list_processes()          # prime cpu_percent deltas
    time.sleep(0.5)
    procs = list_processes()

    by = args.by or "cpu"
    if by == "cpu":
        procs.sort(key=lambda p: p.cpu_percent, reverse=True)
    else:
        procs.sort(key=lambda p: p.private_mb, reverse=True)

    n = args.n or 15
    print(f"{'PID':>7}  {'CPU%':>6}  {'MB':>8}  NAME")
    print("-" * 42)
    for p in procs[:n]:
        print(f"{p.pid:>7}  {p.cpu_percent:>6.1f}  {p.private_mb:>8.1f}  {p.name}")


def cmd_inspect(args: argparse.Namespace) -> None:
    from optimizer.tools.processes import get_process_details
    from optimizer.tools.safety import check_protection, looks_disguised
    from optimizer.tools.knowledge import lookup_known_process
    from optimizer.tools.signature import get_signer

    info = get_process_details(args.pid)
    if info is None:
        print(f"Process {args.pid} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"PID:        {info.pid}")
    print(f"Name:       {info.name}")
    print(f"Exe:        {info.exe or '(unknown)'}")
    print(f"User:       {info.username or '(unknown)'}")
    print(f"Parent:     {info.parent_name or '?'} (ppid {info.ppid})")
    uptime = f"{info.uptime_s:.0f}s" if info.uptime_s is not None else "unknown"
    print(f"Uptime:     {uptime}")
    print(f"CPU:        {info.cpu_percent:.1f}%")
    print(f"Private MB: {info.private_mb:.1f}")
    print(f"Threads:    {info.num_threads}")
    print(f"Priority:   {info.priority}")

    protect = check_protection(info.name, info.exe, info.username, info.pid)
    if protect:
        print(f"[PROTECTED] {protect}")
    if looks_disguised(info.name, info.exe):
        print("[WARNING]   Protected name running outside C:\\Windows\\ — possible malware")

    kp = lookup_known_process(info.name, info.exe)
    if kp:
        print(f"[Known]     {kp.category}: {kp.description}")

    if info.exe:
        signer = get_signer(info.exe)
        if signer:
            print(f"[Signed by] {signer}")


def cmd_act(args: argparse.Namespace) -> None:
    from optimizer.tools.processes import get_process_details
    from optimizer.models import ProcessRef
    from optimizer.tools import actions

    info = get_process_details(args.pid)
    if info is None:
        print(f"Process {args.pid} not found.", file=sys.stderr)
        sys.exit(1)

    ref = ProcessRef(
        pid=info.pid,
        create_time=info.create_time,
        name=info.name,
        exe=info.exe,
    )

    action_map = {
        "lower":       actions.lower_priority,
        "efficiency":  actions.set_efficiency_mode,
        "suspend":     actions.suspend,
        "close":       actions.close_gracefully,
        "terminate":   actions.terminate,
    }

    fn = action_map[args.action]
    result = fn(ref, dry_run=args.dry_run)

    label = "DRY RUN" if args.dry_run else ("OK" if result.ok else "FAILED")
    msg = result.reason or "done"
    print(f"[{label}] {msg}")
    if result.undo:
        print(f"  undo info: {result.undo}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m optimizer.tools",
        description="Windows Optimizer tool layer CLI",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="command")

    sub.add_parser("pressure", help="Show system pressure metrics")

    top_p = sub.add_parser("top", help="List top processes")
    top_p.add_argument("--by", choices=["cpu", "mem"], default="cpu",
                       help="Sort key (default: cpu)")
    top_p.add_argument("-n", type=int, default=15, metavar="N",
                       help="Number of rows to show (default: 15)")

    insp_p = sub.add_parser("inspect", help="Detailed info for one process")
    insp_p.add_argument("pid", type=int)

    act_p = sub.add_parser("act", help="Apply an action to a process")
    act_p.add_argument("pid", type=int)
    act_p.add_argument(
        "action",
        choices=["lower", "efficiency", "suspend", "close", "terminate"],
    )
    act_p.add_argument("--dry-run", action="store_true",
                       help="Check and log without changing anything")

    args = parser.parse_args()

    dispatch = {
        "pressure": cmd_pressure,
        "top":      cmd_top,
        "inspect":  cmd_inspect,
        "act":      cmd_act,
    }

    fn = dispatch.get(args.cmd)
    if fn is None:
        parser.print_help()
        sys.exit(0)
    fn(args)


if __name__ == "__main__":
    main()
