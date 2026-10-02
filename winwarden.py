"""
WinWarden — process optimizer.
Run directly:  python winwarden.py
Or after install:  winwarden
"""
from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from tkinter import messagebox, ttk

_CPU_THRESH = 2.0
_MEM_THRESH = 150.0
_SCAN_MS    = 30_000   # scan costs ~2-8s on Windows; 30s interval is safe
_MY_PID     = os.getpid()


# ── data ──────────────────────────────────────────────────────────────────────

@dataclass
class _Row:
    pid: int
    name: str
    exe: str
    create_time: float
    cpu: float
    mem: float
    reason: str


@dataclass
class _LogEntry:
    ts: str          # "HH:MM:SS"
    action: str
    process: str
    pid: int
    ok: bool
    detail: str


# ── scan ──────────────────────────────────────────────────────────────────────

def _scan() -> list[_Row]:
    from optimizer.tools.processes import list_processes
    out: list[_Row] = []
    for p in list_processes():
        if p.pid == _MY_PID:
            continue
        c = p.cpu_percent >= _CPU_THRESH
        m = p.wset_mb     >= _MEM_THRESH
        if not (c or m):
            continue
        parts: list[str] = []
        if c: parts.append(f"CPU {p.cpu_percent:.0f}%")
        if m: parts.append(f"RAM {p.wset_mb:.0f} MB")
        out.append(_Row(p.pid, p.name, p.exe or "", p.create_time,
                        p.cpu_percent, p.wset_mb, " · ".join(parts)))
    out.sort(key=lambda r: r.cpu + r.mem / 100, reverse=True)
    return out


# ── action metadata ───────────────────────────────────────────────────────────

_ACTIONS: dict[str, tuple[str, str]] = {
    "lower":   ("Lower Priority",
                "Drops to Below Normal. The process keeps running but yields CPU "
                "to active apps when the system is busy. Reversible."),
    "eco":     ("Efficiency Mode",
                "Idle priority + EcoQoS throttling — same as Task Manager's "
                "Efficiency Mode. Best for idle background services. Reversible."),
    "suspend": ("Suspend",
                "Freezes the process. Zero CPU, memory stays in RAM. "
                "Resumes from exactly where it paused. Reversible."),
    "close":   ("Close Gracefully",
                "Sends WM_CLOSE to all windows — same as clicking ✕. "
                "App handles its own shutdown. Cannot be undone."),
    "kill":    ("Force Kill",
                "Terminates immediately via TerminateProcess. No cleanup. "
                "Use only for stuck processes. Cannot be undone."),
}

_STATUS_LABEL: dict[str, str] = {
    "lower":   "Throttled",
    "eco":     "Eco Mode",
    "suspend": "Suspended",
    "close":   "Closed",
    "kill":    "Killed",
}


# ── app ───────────────────────────────────────────────────────────────────────

class _App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("WinWarden")
        self.minsize(980, 600)
        self.geometry("1100x680")
        self._closed = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<F5>", lambda _: self._scan_now())

        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

        self._q: queue.Queue[list[_Row]]     = queue.Queue()
        self._rows: list[_Row]               = []
        self._sel: _Row | None               = None
        self._status_map: dict[int, str]     = {}   # pid → status label
        self._log_entries: list[_LogEntry]   = []

        self._build()
        self._load_history()
        self._poll()
        self._scan_now()

    # ── layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)   # row 2 = paned window

        s = ttk.Style()
        s.configure("Treeview", rowheight=22)
        s.configure("Treeview.Cell", padding=(4, 0))
        s.configure("Danger.TButton", foreground="#c00000")

        # ── toolbar ───────────────────────────────────────────────────────────
        tb = ttk.Frame(self, padding=(10, 6))
        tb.grid(row=0, column=0, sticky="ew")

        ttk.Label(tb, text="WinWarden", font=("", 13, "bold")).pack(side="left")
        ttk.Label(tb, text=" — process optimizer", foreground="#777").pack(side="left")

        self._v_count = tk.StringVar(value="scanning…")
        ttk.Label(tb, textvariable=self._v_count, foreground="#555",
                  font=("", 9)).pack(side="left", padx=(14, 0))

        ttk.Button(tb, text="⟳  Refresh Now", command=self._scan_now).pack(side="right")

        ttk.Separator(self, orient="horizontal").grid(row=1, column=0, sticky="ew")

        # ── vertical paned window: top (table+details) | bottom (log) ─────────
        vpane = ttk.PanedWindow(self, orient="vertical")
        vpane.grid(row=2, column=0, sticky="nsew", padx=6, pady=(6, 0))

        # top pane: horizontal table | details
        top = ttk.PanedWindow(vpane, orient="horizontal")
        vpane.add(top, weight=3)

        # left: process table
        lf = ttk.Frame(top, padding=(0, 0, 2, 0))
        top.add(lf, weight=3)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(1, weight=1)

        ttk.Label(lf, text="Flagged Processes", font=("", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))

        self._tv = ttk.Treeview(
            lf,
            columns=("name", "pid", "cpu", "mem", "status", "reason"),
            show="headings",
            selectmode="browse",
        )
        for col, text, w, stretch, anchor in [
            ("name",   "Process",    170, True,  "w"),
            ("pid",    "PID",         60, False, "e"),
            ("cpu",    "CPU %",       62, False, "e"),
            ("mem",    "RAM MB",      68, False, "e"),
            ("status", "Status",      88, False, "w"),
            ("reason", "Flagged for",  0, True,  "w"),
        ]:
            self._tv.heading(col, text=text, anchor=("center" if anchor == "e" else "w"))
            kw: dict = {"stretch": stretch, "anchor": anchor}
            if w:
                kw["width"] = w
            self._tv.column(col, **kw)

        self._tv.tag_configure("throttled", foreground="#c07000")
        self._tv.tag_configure("suspended", foreground="#0070c0")
        self._tv.tag_configure("eco",       foreground="#007040")

        sb = ttk.Scrollbar(lf, orient="vertical", command=self._tv.yview)
        self._tv.configure(yscrollcommand=sb.set)
        self._tv.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        self._tv.bind("<<TreeviewSelect>>", self._on_select)

        # right: details + actions
        rf = ttk.Frame(top, padding=(8, 4, 4, 4))
        top.add(rf, weight=2)
        rf.columnconfigure(0, weight=1)

        self._v_name = tk.StringVar(value="—")
        ttk.Label(rf, textvariable=self._v_name, font=("", 12, "bold"),
                  wraplength=330).pack(anchor="w")

        self._v_meta = tk.StringVar()
        ttk.Label(rf, textvariable=self._v_meta, foreground="#666",
                  wraplength=330).pack(anchor="w", pady=(1, 0))

        ttk.Separator(rf, orient="horizontal").pack(fill="x", pady=(8, 6))

        ttk.Label(rf, text="Why flagged", font=("", 9, "bold"),
                  foreground="#333").pack(anchor="w")
        self._lbl_why = ttk.Label(rf, text="Select a process to see details.",
                                  wraplength=330, justify="left", foreground="#555")
        self._lbl_why.pack(anchor="w", pady=(3, 0))

        ttk.Separator(rf, orient="horizontal").pack(fill="x", pady=(8, 6))

        ttk.Label(rf, text="Actions", font=("", 9, "bold"),
                  foreground="#333").pack(anchor="w", pady=(0, 4))
        # 2-column button grid
        btn_grid = ttk.Frame(rf)
        btn_grid.pack(fill="x")
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)
        self._btns: dict[str, ttk.Button] = {}
        positions = [("lower", 0, 0), ("eco",   0, 1),
                     ("suspend", 1, 0), ("close", 1, 1),
                     ("kill",  2, 0)]
        for key, row, col in positions:
            label, _ = _ACTIONS[key]
            style = "Danger.TButton" if key == "kill" else "TButton"
            b = ttk.Button(btn_grid, text=label, state="disabled", style=style,
                           command=lambda k=key: self._act(k))
            b.grid(row=row, column=col, sticky="ew", padx=(0, 2) if col == 0 else (2, 0), pady=2)
            self._btns[key] = b

        ttk.Separator(rf, orient="horizontal").pack(fill="x", pady=(8, 6))

        ttk.Label(rf, text="Last result", font=("", 9, "bold"),
                  foreground="#333").pack(anchor="w")
        self._lbl_result = ttk.Label(rf, text="—", wraplength=330, justify="left",
                                     foreground="#888")
        self._lbl_result.pack(anchor="w", pady=(3, 0))

        # bottom pane: action log
        log_frame = ttk.Frame(vpane, padding=(0, 4, 0, 0))
        vpane.add(log_frame, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        log_hdr = ttk.Frame(log_frame)
        log_hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(log_hdr, text="Action History", font=("", 9, "bold")).pack(side="left")
        ttk.Button(log_hdr, text="Clear", command=self._clear_log).pack(side="right")

        self._log_tv = ttk.Treeview(
            log_frame,
            columns=("ts", "action", "process", "pid", "result"),
            show="headings",
            height=6,
        )
        for col, text, w, anchor in [
            ("ts",      "Time",      72, "w"),
            ("action",  "Action",   118, "w"),
            ("process", "Process",  165, "w"),
            ("pid",     "PID",       58, "e"),
            ("result",  "Result",     0, "w"),
        ]:
            self._log_tv.heading(col, text=text, anchor=("center" if anchor == "e" else "w"))
            self._log_tv.column(col, width=w, stretch=(w == 0), anchor=anchor)

        self._log_tv.tag_configure("ok",  foreground="#007040")
        self._log_tv.tag_configure("err", foreground="#c00000")

        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_tv.yview)
        self._log_tv.configure(yscrollcommand=log_sb.set)
        self._log_tv.grid(row=1, column=0, sticky="nsew")
        log_sb.grid(row=1, column=1, sticky="ns")

        # ── status bar ────────────────────────────────────────────────────────
        self._v_status = tk.StringVar(value="Starting scan…")
        ttk.Label(self, textvariable=self._v_status, relief="sunken",
                  anchor="w", padding=(8, 3), foreground="#555").grid(
            row=3, column=0, sticky="ew")

    # ── scanning ──────────────────────────────────────────────────────────────

    def _scan_now(self) -> None:
        self._v_status.set("Scanning…")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        t0 = time.perf_counter()
        try:
            rows = _scan()
        except Exception as exc:
            rows = []
            if not self._closed:
                self.after(0, self._v_status.set, f"Scan error: {exc}")
        elapsed = (time.perf_counter() - t0) * 1000
        self._q.put((rows, elapsed))
        if not self._closed:
            self.after(_SCAN_MS, self._scan_now)

    def _poll(self) -> None:
        if self._closed:
            return
        try:
            rows, elapsed_ms = self._q.get_nowait()
            self._refresh(rows, elapsed_ms)
        except queue.Empty:
            pass
        self.after(300, self._poll)

    def _refresh(self, rows: list[_Row], elapsed_ms: float) -> None:
        self._rows = rows
        sel_pid = self._sel.pid if self._sel else None

        self._tv.delete(*self._tv.get_children())
        for r in rows:
            status = self._status_map.get(r.pid, "")
            tag = {"Throttled": "throttled", "Eco Mode": "eco",
                   "Suspended": "suspended"}.get(status, "")
            self._tv.insert("", "end", iid=str(r.pid), tags=(tag,),
                            values=(r.name, r.pid,
                                    f"{r.cpu:.1f}", f"{r.mem:.0f}",
                                    status, r.reason))
            if r.pid == sel_pid:
                self._tv.selection_set(str(r.pid))

        n = len(rows)
        self._v_count.set(f"{n} process{'es' if n != 1 else ''} flagged")
        self._v_status.set(
            f"Last scan: {datetime.now().strftime('%H:%M:%S')}  "
            f"({elapsed_ms:.0f} ms)  •  next in {_SCAN_MS // 1000}s  •  F5 to refresh"
        )

        if sel_pid and not any(r.pid == sel_pid for r in rows):
            self._sel = None
            self._clear_detail()

    # ── detail panel ──────────────────────────────────────────────────────────

    def _on_select(self, _e: object) -> None:
        sel = self._tv.selection()
        if not sel:
            return
        row = next((r for r in self._rows if r.pid == int(sel[0])), None)
        if row:
            self._sel = row
            self._show(row)

    def _show(self, row: _Row) -> None:
        self._v_name.set(row.name)
        self._v_meta.set(f"PID {row.pid}  •  {row.exe or '(path unknown)'}")

        parts: list[str] = []
        if row.cpu >= _CPU_THRESH:
            parts.append(
                f"CPU is {row.cpu:.1f}% — consuming compute cycles in the background "
                "while you may not be actively using it."
            )
        if row.mem >= _MEM_THRESH:
            parts.append(
                f"Working set is {row.mem:.0f} MB of physical RAM currently occupied. "
                "This is real memory pages, not virtual address space."
            )
        try:
            from optimizer.tools.knowledge import lookup_known_process
            kp = lookup_known_process(row.name, row.exe)
            if kp:
                note = {"bloat":            "Generally safe to throttle.",
                        "useful_background":"Useful background service — throttle carefully.",
                        "user_app":         "One of your applications.",
                        }.get(kp.category, "")
                parts.append(f"{kp.description}  {note}".strip())
        except Exception:
            pass

        self._lbl_why.configure(text="\n\n".join(parts) or "No additional information.")
        self._lbl_result.configure(text="—", foreground="")
        self._check_btns(row)

    def _check_btns(self, row: _Row) -> None:
        from optimizer.models import ProcessRef
        from optimizer.tools.actions import check_safe
        from optimizer.tools.windows import get_process_windows

        ref = ProcessRef(pid=row.pid, name=row.name, exe=row.exe,
                         create_time=row.create_time)
        block  = check_safe(ref)
        windowed = get_process_windows() if block is None else {}
        safe = block is None

        self._btns["lower"].configure(  state="normal" if safe else "disabled")
        self._btns["eco"].configure(    state="normal" if safe else "disabled")
        self._btns["suspend"].configure(state="normal" if safe else "disabled")
        self._btns["close"].configure(  state="normal" if (safe and row.pid in windowed) else "disabled")
        self._btns["kill"].configure(   state="normal" if safe else "disabled")

        if block:
            self._lbl_result.configure(text=f"Blocked: {block}", foreground="#888")

    def _clear_detail(self) -> None:
        self._v_name.set("—")
        self._v_meta.set("")
        self._lbl_why.configure(text="Select a process.")
        self._lbl_result.configure(text="—", foreground="")
        for b in self._btns.values():
            b.configure(state="disabled")

    # ── actions ───────────────────────────────────────────────────────────────

    def _act(self, key: str) -> None:
        if not self._sel:
            return
        row = self._sel
        label, explain = _ACTIONS[key]

        if key in ("close", "kill"):
            if not messagebox.askyesno(
                "Confirm",
                f"{explain}\n\nApply '{label}' to {row.name} (PID {row.pid})?",
                icon="warning",
            ):
                return

        from optimizer.models import ProcessRef
        from optimizer.tools.actions import (
            close_gracefully, lower_priority, set_efficiency_mode, suspend, terminate,
        )
        ref = ProcessRef(pid=row.pid, name=row.name, exe=row.exe,
                         create_time=row.create_time)
        fns = {
            "lower":   lambda: lower_priority(ref),
            "eco":     lambda: set_efficiency_mode(ref, on=True),
            "suspend": lambda: suspend(ref),
            "close":   lambda: close_gracefully(ref),
            "kill":    lambda: terminate(ref),
        }
        result = fns[key]()

        ts = datetime.now().strftime("%H:%M:%S")
        if result.ok:
            self._status_map[row.pid] = _STATUS_LABEL[key]
            detail = "Done"
            self._lbl_result.configure(
                text=f"✓  {label} applied to {row.name}.",
                foreground="#007040",
            )
            self._v_status.set(f"✓  {label} → {row.name} (PID {row.pid})")
            self.after(800, self._scan_now)
        else:
            detail = result.reason
            self._lbl_result.configure(
                text=f"✗  Failed: {result.reason}",
                foreground="#c00000",
            )
            self._v_status.set(f"✗  {label} failed on {row.name}: {result.reason}")

        self._add_log(_LogEntry(ts=ts, action=label, process=row.name,
                                pid=row.pid, ok=result.ok, detail=detail))

    def _add_log(self, entry: _LogEntry) -> None:
        self._log_entries.append(entry)
        icon = "✓" if entry.ok else "✗"
        tag  = "ok" if entry.ok else "err"
        iid  = str(len(self._log_entries))
        self._log_tv.insert("", 0, iid=iid, tags=(tag,),
                             values=(entry.ts, entry.action, entry.process,
                                     entry.pid, f"{icon}  {entry.detail}"))

    def _load_history(self) -> None:
        from optimizer import journal
        from datetime import datetime
        for e in journal.recent(40):
            ok = e.status in ("done", "active", "undone")
            ts = datetime.fromtimestamp(e.ts).strftime("%H:%M:%S")
            icon = "✓" if ok else "✗"
            detail = e.note or e.status
            tag = "ok" if ok else "err"
            iid = f"j{e.id}"
            self._log_tv.insert("", "end", iid=iid, tags=(tag,),
                                values=(ts, e.action, e.name, e.pid,
                                        f"{icon}  {detail}"))

    def _clear_log(self) -> None:
        self._log_tv.delete(*self._log_tv.get_children())
        self._log_entries.clear()

    def _on_close(self) -> None:
        self._closed = True
        self.destroy()


if __name__ == "__main__":
    # Guard for multiprocessing on Windows (benchmark imports this module)
    import multiprocessing
    multiprocessing.freeze_support()
    _App().mainloop()
