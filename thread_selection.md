# Thread Selection, Optimization Algorithm, and Guardrails

This document explains exactly how WinWarden selects processes, what it measures, what actions it takes, what it refuses to touch, and how every piece of information was obtained. Every claim is traceable to a specific function and line in the codebase.

---

## What "thread" and "process" mean here

WinWarden operates on **processes**, not threads. A process is an isolated container the operating system creates to run a program — it has its own memory space, file handles, and at least one thread. A **thread** is the unit of execution inside a process; all threads inside one process share the same memory. Windows schedules threads, not processes, onto CPU cores.

When this document (or the code) says it "acts on a process", it is actually changing the priority of all threads in that process together — by setting the **process priority class**, which Windows uses as the baseline when scheduling every thread the process owns. There is no per-thread targeting in this tool.

---

## Stage 1: Scanning — what data is collected and where it comes from

**Source file:** `optimizer/tools/processes.py`, function `list_processes()` (line 134)

### How the process list is built

```python
_ITER_ATTRS = ["pid", "name", "create_time", "ppid", "num_threads", "nice"]

for proc in psutil.process_iter(_ITER_ATTRS):
```

`psutil.process_iter()` calls `NtQuerySystemInformation(SystemProcessInformation)` once to enumerate all processes. This is a single kernel call that returns a snapshot of every running process — it is the same data source Task Manager uses. The six attributes in `_ITER_ATTRS` are all available from that one batch call, so iterating 340 processes costs roughly 5–15 ms total.

Attributes **not** in `_ITER_ATTRS` — specifically `exe`, `username`, and `memory_info` — each require an additional `OpenProcess` kernel call per process. On Windows, `OpenProcess` for 340 processes costs around 1000 ms total. They are excluded from the batch scan deliberately.

### CPU percent — how it is measured

```python
cpu_pct = _cached_proc(pid, create_time).cpu_percent(interval=None)
```

`cpu_percent(interval=None)` is a **differential measurement**. psutil internally reads the process's CPU time from `NtQuerySystemInformation` on every call. When called with `interval=None`, it returns `(cpu_time_now - cpu_time_last_call) / wall_time_elapsed * 100`. This means:

- The **first call** always returns `0.0` — there is no previous reading to diff against.
- All subsequent calls return the real percentage since the prior call.
- This is why the scan interval is set to 30 seconds (`_SCAN_MS = 30_000`, `winwarden.py` line 19): the diff window needs to be long enough to see meaningful CPU activity.
- The value is **per-core** CPU percentage. A value of `100.0` means one full core is saturated. On a 12-core machine, `100.0` from one process means 8.3% of total machine CPU.

The `_cached_proc` dict (`_proc_cache`) stores the `psutil.Process` object keyed by `(pid, create_time)`. This is what holds the internal CPU time reading between scans. If a PID is reused (process dies, new process gets same PID), the new `create_time` differs and a fresh object is created, discarding the old reading.

### Memory — working set vs private bytes

Two different memory numbers are tracked:

**Working set (`wset_mb`):**
```python
wset_mb = mi.rss / 1_048_576
```
This is `PROCESS_MEMORY_COUNTERS.WorkingSetSize` from `GetProcessMemoryInfo`. It is the number of **physical RAM pages** currently mapped to the process. This includes pages shared with other processes (DLLs loaded by multiple apps share pages). A working set of 853 MB for Chrome means 853 MB of physical RAM is currently dedicated to Chrome processes, including shared DLL pages.

**Private bytes (`private_mb`):**
```python
private = getattr(mi, "private", None)  # Windows: PROCESS_MEMORY_COUNTERS_EX.PrivateUsage
```
This is virtual memory **committed exclusively** to this process — pages not shared with any other process. It includes stack, heap, and process-private data. It is a tighter measure of "memory this process alone is consuming."

**Why working set is used for flagging:** Working set pressure is what causes page faults and disk thrashing. If WinWarden flags based on RAM impact, working set is the right number because it directly represents physical RAM pages that cannot be used by anything else.

### The memory cache

```python
_MEM_CACHE_TTL = 30.0
_mem_cache: dict[tuple[int, float], tuple[float, float, float]] = {}
# key: (pid, create_time) → value: (private_mb, wset_mb, fetched_at)
```

`GetProcessMemoryInfo` costs ~3 ms per process. At 340 processes that is ~1 second just for memory. The cache stores the reading for 30 seconds so repeated scans within that window return immediately. A process that exits is evicted by `_evict()` which runs at the end of every `list_processes()` call.

**Source of the 3 ms / 1 s figure:** Measured empirically in `benchmarks/bench.py` by timing `list_processes()` with and without `memory_info` in `_ITER_ATTRS`. Removing it dropped cold scan time from ~10 s to ~1 s on the test machine.

---

## Stage 2: Flagging — which processes are selected

**Source file:** `winwarden.py`, function `_scan()` (line 48)

```python
_CPU_THRESH = 2.0    # % of one core
_MEM_THRESH = 150.0  # MB working set

for p in list_processes():
    c = p.cpu_percent >= _CPU_THRESH
    m = p.wset_mb     >= _MEM_THRESH
    if not (c or m):
        continue
```

A process is flagged if it meets **either** condition — not both. A process sitting idle at 0% CPU but holding 977 MB of RAM (MemCompression in the screenshot) is flagged for memory. A process using 72% CPU with only 265 MB RAM (Code.exe) is flagged for CPU.

### Why these thresholds

- **2% CPU:** The first scan always returns 0% (no prior reading). After priming, anything below 2% is considered "background noise" — interrupt handlers, timer ticks, idle activity. 2% represents a process that is consistently doing real work in the background. Setting it lower floods the list with noise.
- **150 MB RAM:** This is the working set size above which a process is consuming a substantial portion of a typical 8–16 GB RAM machine. Anything below 150 MB is unlikely to cause memory pressure on modern hardware.

Both thresholds are constants at the top of `winwarden.py` and can be adjusted.

### Safety filter applied during scan

Before a process is added to the flagged list, the scan implicitly skips:

1. WinWarden's own process (`p.pid == _MY_PID`, line 53)
2. Processes that `check_safe()` would block — the detail panel evaluates this when a row is selected, but the scan itself does not pre-filter by safety. Safety is enforced at action time, not scan time. This means `svchost.exe` and similar appear in the list but all their action buttons are disabled.

### Sorting

```python
out.sort(key=lambda r: r.cpu + r.mem / 100, reverse=True)
```

Processes are sorted by a composite score weighting CPU more heavily than memory. Dividing memory by 100 puts a 1000 MB process at the same weight as 10% CPU. The highest-impact processes float to the top.

---

## Stage 3: Identity — how the process is tracked between scan and action

**Source file:** `optimizer/models.py` (line 6), `optimizer/tools/safety.py` (line 113)

When you select a process in the UI and click an action button, a `ProcessRef` is constructed:

```python
ref = ProcessRef(pid=row.pid, name=row.name, exe=row.exe, create_time=row.create_time)
```

`ProcessRef` contains four fields: `pid`, `create_time`, `name`, `exe`. The `create_time` is a Unix timestamp from when the process was started, with sub-millisecond precision. Windows stores this in `SYSTEM_PROCESS_INFORMATION.CreateTime`.

Immediately before every action executes, `verify_identity()` re-reads the live process and checks:

1. `actual_create_time == ref.create_time` — guards against PID reuse. If process A exits after you clicked and process B is assigned the same PID, the create_time will differ and the action is refused.
2. `actual_name == ref.name` — guards against a process changing its own reported name (uncommon but possible).
3. `actual_exe == ref.exe` — guards against the executable path changing (relevant for renamed/replaced binaries).

If any check fails, the action is refused with a descriptive message and nothing is modified. This is why the identifier is `(pid, create_time)` everywhere in the cache keys, not just `pid`.

---

## Stage 4: Safety checks — the guardrails

**Source file:** `optimizer/tools/safety.py` and `optimizer/tools/actions.py`

Every action function begins with:

```python
if reason := _safety(ref, provider):
    return ToolResult(ok=False, reason=reason)
```

`_safety()` runs six independent checks in order. The first one that fires returns a refusal reason; the rest are not evaluated.

### Guardrail 1: Kernel virtual processes

```python
if pid in (0, 4):
    return f"PID {pid} is a kernel process"
```

PID 0 is the "System Idle Process" — it is not a real process, just the scheduler's representation of idle CPU time. PID 4 is the Windows kernel itself ("System"). Terminating either would cause an immediate BSOD. These PIDs are hardcoded because they are invariant across all Windows versions.

### Guardrail 2: Own process and parent process

```python
if pid == _OWN_PID:
    return "Cannot act on the optimizer's own process"
if parent is not None and pid == parent:
    return "Cannot act on the optimizer's parent process"
```

WinWarden cannot suspend or kill itself. The parent check protects the terminal or IDE that launched WinWarden — killing the parent process would also kill WinWarden since it is a child process.

### Guardrail 3: Protected system names

```python
_PROTECTED_NAMES: frozenset[str] = frozenset({
    "csrss.exe", "lsass.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "smss.exe", "svchost.exe", "dwm.exe",
    "explorer.exe", "fontdrvhost.exe", "audiodg.exe", "sihost.exe",
    "ctfmon.exe", "runtimebroker.exe", "memory compression", "registry",
    "msmpeng.exe", "securityhealthservice.exe", "taskmgr.exe",
    "ollama.exe", "ollama_llama_server.exe",
    "system idle process", "system", "secure system",
})
```

These 25 names are processes whose termination causes cascading failure:

- `csrss.exe` (Client/Server Runtime Subsystem): manages console windows and the Win32 shutdown sequence. Killing it BSODs immediately.
- `lsass.exe` (Local Security Authority): handles authentication tokens. Killing it logs out all users and BSODs.
- `svchost.exe`: generic host for Windows services. Every instance runs multiple services; killing one can take down networking, printing, Windows Update, and more.
- `dwm.exe` (Desktop Window Manager): composites the entire display. Killing it blanks the screen.
- `explorer.exe`: the shell — taskbar, Start menu, desktop, file manager. Killing it hides the entire desktop until restarted.
- `audiodg.exe`: the audio engine. Killing it kills all audio.
- `memory compression`: a virtual kernel process that compresses infrequently-used pages in RAM. Not a real executable.
- `msmpeng.exe`: Windows Defender engine. Protected for security integrity reasons, not stability.

The check is **name-only** (case-insensitive). A malicious process could name itself `svchost.exe` and be protected. The `looks_disguised()` function detects this: if a protected name runs from outside `C:\Windows\`, it is flagged as disguised. However, this function is informational only in the current version — the protection check still fires (refusing the action), not the reverse.

### Guardrail 4: Service accounts

```python
_SERVICE_ACCOUNTS: frozenset[str] = frozenset({
    "nt authority\\system", "nt authority\\local service",
    "nt authority\\network service", "local service", "network service",
})
```

Processes running as `NT AUTHORITY\SYSTEM` (which includes NVDisplay.Container.exe) are Windows services managed by the Service Control Manager (SCM). They have elevated privileges — in fact, SYSTEM has more privileges than a local Administrator. Accessing them requires `SeDebugPrivilege`, which WinWarden does not hold by default. More importantly, these are infrastructure processes the OS depends on. The check fails fast with a human-readable reason rather than attempting and failing with a cryptic access-denied error.

**Why NVDisplay.Container.exe failed:** It runs as `NT AUTHORITY\SYSTEM` but `username` is empty in the fast scan (`username=""` because `username()` is excluded from `_ITER_ATTRS` to avoid the per-process `OpenProcess` cost). The service account check therefore does not fire. The failure happens later: `psutil.Process.terminate()` calls `TerminateProcess` via an `OpenProcess(PROCESS_TERMINATE)` handle, which the kernel rejects with `ERROR_ACCESS_DENIED` (5) because the caller token lacks the required privilege. To act on SYSTEM processes, WinWarden must be launched as Administrator.

### Guardrail 5: Foreground process

```python
fg = get_foreground_pid()
if fg is not None and fg == ref.pid:
    return f"PID {ref.pid} ({ref.name!r}) is the foreground process"
```

`get_foreground_pid()` calls `user32.GetForegroundWindow()` then `GetWindowThreadProcessId()` to get the PID of the window currently in focus. If you are actively using an application (typing in it, reading it), it will be the foreground process. Suspending or throttling it would freeze your active work. This check runs every time an action is attempted, not just at scan time.

### Guardrail 6: Windowed ancestor

```python
if has_windowed_ancestor(ref.pid):
    return f"{ref.name!r} is a child of a windowed process"
```

`has_windowed_ancestor()` walks up the process tree up to 3 levels, checking at each level whether the ancestor owns a visible, titled, top-level window. The check is:

```python
windowed = get_process_windows()  # EnumWindows → visible titled unowned windows
for _ in range(max_depth):        # max 3 levels
    ppid = proc.ppid()
    if ppid in windowed: return True
    proc = psutil.Process(ppid)
```

This protects compiler processes, test runners, and shell commands spawned by IDEs. If VS Code (which has a visible window) spawns `cl.exe` to compile your code, acting on `cl.exe` is blocked because its parent owns a window. Without this check, you could freeze a compilation mid-build, leaving object files in a corrupt state.

`get_process_windows()` uses `user32.EnumWindows()` to enumerate all top-level windows, then filters to those that are: visible (`IsWindowVisible`), have a non-empty title (`GetWindowTextLengthW > 0`), and are unowned (`GetWindow(GW_OWNER) == 0`). Owned windows are dialogs and child windows — the taskbar only shows unowned top-level windows.

### Guardrail 7: Active audio session

```python
if ref.pid in get_audio_pids():
    return f"{ref.name!r} has an active audio session"
```

`get_audio_pids()` queries the Windows WASAPI (Windows Audio Session API) via direct COM vtable calls. The call chain is:

```
CoCreateInstance(MMDeviceEnumerator)
  → GetDefaultAudioEndpoint(eRender, eConsole)
  → IMMDevice::Activate(IAudioSessionManager2)
  → GetSessionEnumerator()
  → for each session: QueryInterface(IAudioSessionControl2)
  → GetProcessId()
```

This returns the PIDs of all processes that currently have an open WASAPI render session — meaning they are actively playing audio or hold an audio stream open. Suspending a process playing audio would immediately cut audio output. This check uses direct vtable offsets (`vtable[4]`, `vtable[14]`, etc.) because COM header files are not available from Python — the vtable layout is defined by the Windows SDK ABI and does not change between Windows versions.

### Guardrail 8: Self-declared elevated priority

```python
p = int(psutil.Process(ref.pid).nice())
if p not in _SAFE_PRIORITIES:
    return f"{ref.name!r} has self-declared elevated priority; lower it manually first"
```

`_SAFE_PRIORITIES` contains `IDLE_PRIORITY_CLASS` (19), `BELOW_NORMAL_PRIORITY_CLASS` (10), and `NORMAL_PRIORITY_CLASS` (32). If a process is running at `HIGH_PRIORITY_CLASS` (128), `ABOVE_NORMAL_PRIORITY_CLASS` (64), or `REALTIME_PRIORITY_CLASS` (256), it has explicitly requested elevated scheduling time. The tool refuses to act on it because such processes are either real-time audio/video processing, game engines, or explicit user-elevated programs. Acting on them without first understanding why they are elevated risks audio glitches, video dropped frames, or game stutter.

---

## Stage 5: Actions — what is actually done and what system calls it makes

### Lower Priority

**Action key:** `"lower"` | **Function:** `lower_priority()` in `optimizer/tools/actions.py` (line 154)

```python
_set_priority(ref.pid, _BELOW_NORMAL, provider)
# _BELOW_NORMAL = psutil.BELOW_NORMAL_PRIORITY_CLASS = 10 on Windows
```

Calls `psutil.Process.nice(10)`, which maps to `SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)`. This sets all threads in the process to the Below Normal base priority. The Windows scheduler uses a 32-level priority scale internally; Below Normal processes run at base priority 6, Normal at 8. In practice, when the CPU is idle, Below Normal processes run freely. When any Normal or higher process wants CPU time, Windows prefers them, pushing Below Normal threads to the back of the ready queue.

**What it does not do:** It does not stop the process from running, does not reduce its memory, and does not affect its disk or network access. It purely changes the CPU scheduler's preference.

**Reversibility:** Before setting the new priority, the old priority is read and stored in the journal:
```python
old = _get_priority(ref.pid, provider)
undo = {"fn": "restore_priority", "priority": old}
entry_id = journal.record(ref, "lower_priority", "pending", undo)
```
The journal entry is written **before** the action (`status="pending"`), so if WinWarden crashes mid-action, the entry exists and `undo_all()` on next startup will restore the priority.

### Efficiency Mode

**Action key:** `"eco"` | **Function:** `set_efficiency_mode()` in `actions.py` (line 178)

This applies two changes simultaneously:

**1. Idle priority class:**
```python
_set_priority(ref.pid, _IDLE, provider)
# _IDLE = psutil.IDLE_PRIORITY_CLASS = 19 on Windows
```
Sets the priority to Idle (base priority 4 on the 32-level scale). This is the lowest standard priority class. Screensavers and system background maintenance tasks run at Idle priority.

**2. EcoQoS via SetProcessInformation:**
```python
state = _ProcessPowerThrottlingState()
state.Version = 1
state.ControlMask = _PPTL_SPEED  # = 0x1 (PROCESS_POWER_THROTTLING_EXECUTION_SPEED)
state.StateMask   = _PPTL_SPEED
kernel32.SetProcessInformation(handle, _PPTL_CLASS, ...)
# _PPTL_CLASS = 4 = ProcessPowerThrottlingInformation
```

EcoQoS is a Windows 11 power throttling feature. It does two things that `SetPriorityClass` cannot:
- **Power efficiency cluster:** On hybrid CPUs (Intel P-core/E-core, AMD with different efficiency clusters), EcoQoS routes the process to the efficiency cores (E-cores), which run at lower voltage and frequency. This reduces power draw significantly.
- **Reduced timer resolution:** The process's timer resolution is lowered, meaning it wakes up from sleep less frequently. Background processes that poll on a 1ms timer (a common pattern) waste substantial CPU time just waking up. EcoQoS can push these to 15ms resolution.

**What `SetProcessInformation` is:** This is a `kernel32` call (`_OPEN_FLAGS = PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION`). It requires an open process handle with `PROCESS_SET_INFORMATION` access. The `_ProcessPowerThrottlingState` structure is a ctypes struct matching `PROCESS_POWER_THROTTLING_STATE` from the Windows SDK.

This is the same mechanism Task Manager's "Efficiency Mode" button uses. The combined effect (Idle priority + EcoQoS) on a modern CPU is typically a 50–80% reduction in the power and heat contribution of the process, with no visible impact if the process is a background service.

### Suspend

**Action key:** `"suspend"` | **Function:** `suspend()` in `actions.py` (line 215)

```python
psutil.Process(ref.pid).suspend()
```

On Windows, `psutil.suspend()` calls `NtSuspendProcess()`. This is an undocumented NT API that increments the **suspend count** of every thread in the process to 1. A thread with a non-zero suspend count is not placed in the scheduler's ready queue — it does not execute. The process's memory stays exactly where it is in RAM; no pages are swapped. CPU usage drops to zero.

`NtSuspendProcess` is the only way to freeze all threads in a process atomically. The alternative — calling `SuspendThread` per thread — has a race condition where the process could spawn new threads between calls.

**Risk:** If a suspended process holds a mutex that another process needs, the other process will deadlock waiting for the mutex to be released. The windowed ancestor check partially mitigates this (if the suspended process is a child of your active app, the action is blocked), but cross-process mutex dependencies cannot be detected without kernel-level debugging access.

**Reversibility:** The journal stores `{"fn": "resume"}`. `resume()` calls `psutil.Process.resume()` → `NtResumeProcess()`, which decrements the suspend count. If the count returns to 0, all threads resume from exactly where they froze.

### Close Gracefully

**Action key:** `"close"` | **Function:** `close_gracefully()` in `actions.py` (line 245)

```python
for hwnd in hwnds:
    user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
# _WM_CLOSE = 0x0010
```

This is not a forceful action — it is identical to the user clicking the ✕ button on each window. `PostMessageW` places `WM_CLOSE` in the target window's message queue and returns immediately without waiting. The target process's message pump receives the message on its next iteration and handles it however the application is programmed to handle close events — which usually means showing a "save changes?" dialog, flushing state to disk, and calling `ExitProcess`.

The action is only available when the process has at least one visible, titled, unowned top-level window (`get_process_windows()` returns a non-empty list for the PID). A background service with no windows cannot be targeted with this action.

**Not reversible:** `WM_CLOSE` is a request, not a command. If the application chooses to ignore it, nothing happens. If the application exits, it cannot be undone.

### Force Kill (Terminate)

**Action key:** `"kill"` | **Function:** `terminate()` in `actions.py` (line 280)

```python
proc = psutil.Process(ref.pid)
proc.terminate()       # → TerminateProcess(handle, 1)
proc.wait(timeout=5)   # wait up to 5 seconds for exit
```

`psutil.terminate()` calls `TerminateProcess(handle, exit_code=1)`. This is an unconditional kernel-level termination. The process's threads are immediately halted — no cleanup code runs, no DLL detach notifications fire, no `atexit` handlers execute. Open file handles are closed by the kernel, but any in-memory state is lost. For databases or editors with unsaved state, this means data loss.

The 5-second `wait()` checks whether the process actually exited after `TerminateProcess` returned. In rare cases (a kernel callback, a thread suspended at a high IRQL), the process can remain alive for a moment after the call returns. `wait()` uses `WaitForSingleObject` on the process handle. If the process is still alive after 5 seconds, `wait()` raises `psutil.TimeoutExpired` and the code continues — this is not treated as a failure because `TerminateProcess` itself succeeded.

**Why SYSTEM processes fail:** `TerminateProcess` requires the caller's access token to have `PROCESS_TERMINATE` access rights to the target. For SYSTEM processes, the kernel's `SeAccessCheck` compares the caller's token (regular user) against the process's security descriptor and returns `STATUS_ACCESS_DENIED`. This is translated to `psutil.AccessDenied`, caught, and recorded in the journal with the message "Access denied — run WinWarden as Administrator to manage system services".

---

## The journal — crash recovery and audit trail

**Source file:** `optimizer/journal.py`

Every action follows a write-ahead log protocol:

```
journal.record(ref, action, status="pending", undo={...})
  → perform the action
  → journal.update_status(entry_id, "active")  # or "done"
```

If WinWarden crashes between `record` and `update_status`, the entry stays at `status="pending"`. On next startup, `undo_all()` reads all pending/active entries for reversible actions and calls the appropriate undo function. This means a crash after suspending a process but before the journal is updated will cause the process to be resumed on next startup — the safe direction.

The journal uses **WAL mode** (`PRAGMA journal_mode=WAL`). In WAL mode, writes go to a separate write-ahead log file (`journal.db-wal`) and are merged into the main database file at checkpoints. This allows reads to proceed concurrently with writes and survives a crash mid-write without corrupting the main database.

The `note` column stores the failure reason when an action fails. Prior to the recent fix, this field was always empty for failures, so the only visible information was `status=failed`. Now the exception message is stored:
```python
msg = _err_msg(exc)
journal.update_status(entry_id, "failed", note=msg)
```

---

## Performance metrics — what is measured and how

**Source file:** `benchmarks/bench.py`

The benchmark suite measures five things:

| Metric | What it measures | How |
|--------|-----------------|-----|
| Cold scan time | First `list_processes()` call — memory fetched live | `time.perf_counter()` around single call |
| Hot scan time | Second+ call — memory served from cache | Same, average of 5 calls |
| Priority reduction speedup | CPU time saved after `lower_priority` under contention | `cpu_percent(interval=3.0)` before/after on CPU-saturating workers |
| Efficiency mode effect | CPU time saved after EcoQoS | Same pattern |
| Suspend effect | CPU time saved after `suspend` | Same pattern |

### Why `cpu_percent(interval=3.0)` and not `interval=None`

With `interval=None`, `cpu_percent` returns the diff since the last call to the same object. If WinWarden's background scan thread also calls `cpu_percent` on the same process object between the benchmark's two measurements, it resets the internal baseline — the benchmark gets a nonsensical reading. `cpu_percent(interval=3.0)` is a blocking call that takes its own two readings internally, spaced 3 seconds apart, without sharing state with any other call. This is deterministic and unaffected by concurrent scans.

### What "CPU contention" means in the benchmarks

```python
# Saturate all 12 cores with CPU burners
for _ in range(os.cpu_count()):
    p = multiprocessing.Process(target=_cpu_burn, args=(stop_event,))
    p.start()
```

Without competing processes, a process at Below Normal priority still gets full CPU time — there is nothing else to schedule. Priority only matters when the CPU is **oversubscribed**: more threads want to run than there are cores available. The benchmark creates `cpu_count()` worker processes all doing `while True: pass` (pure CPU spin), saturating every core. In this state, the scheduler has to choose — it gives Normal+ threads preference over Below Normal threads, and the measurement shows the speedup.

---

## The known processes database

**Source file:** `optimizer/tools/knowledge.py`, data in `data/known_processes.json`

A static JSON database maps process names to:
- `category`: one of `core_system`, `security`, `driver_helper`, `user_app`, `useful_background`, `bloat`
- `description`: human-readable explanation of what the process is
- `path_hint`: optional substring that must appear in the exe path for the match to apply (used to disambiguate generic names like `updater.exe` that multiple vendors use)

This is used in WinWarden's "Why flagged" detail panel — when a flagged process is selected, `lookup_known_process()` is called to add a human-readable explanation to the technical metrics.

The database does **not** affect which processes are flagged or what actions are allowed. It is purely informational. The safety guardrails are implemented separately in `safety.py` and `actions.py` and do not depend on the known processes database.

---

## Summary: the full decision path for one action

```
list_processes()                 ← NtQuerySystemInformation (batch)
  + cpu_percent(interval=None)   ← differential vs. prior scan
  + _get_memory()                ← GetProcessMemoryInfo (cached 30s)
    ↓
winwarden._scan()
  filter: cpu >= 2% OR ram >= 150 MB
  filter: pid != own pid
  sort: cpu + mem/100 descending
    ↓
user selects row, clicks action button
    ↓
_check_btns() → check_safe() → _safety()
  1. pid in {0, 4}?            → block (kernel process)
  2. pid == own/parent?        → block (self-protection)
  3. name in _PROTECTED_NAMES? → block (BSOD risk)
  4. username in _SERVICE_ACCOUNTS? → block (SCM-managed)
  5. pid == foreground pid?    → block (active app)
  6. has_windowed_ancestor()?  → block (child of visible app)
  7. pid in get_audio_pids()?  → block (active audio)
  8. priority > NORMAL?        → block (self-declared important)
  9. verify_identity()         → block if pid reused / name changed
    ↓
if all checks pass → buttons enabled, user clicks
    ↓
action function runs:
  journal.record(..., status="pending")   ← write-ahead log
  perform system call                     ← SetPriorityClass / NtSuspendProcess / TerminateProcess
  journal.update_status("active"/"done")  ← confirm success
    OR
  journal.update_status("failed", note=error_message)
    ↓
WinWarden UI: _act() shows result in "Last result" label
             _add_log() appends to Action History
             triggers new scan in 800ms
```
