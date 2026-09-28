# Windows Optimizer — Full Explanation

This document explains the project from first principles. It assumes you know
Python but not how operating systems manage processes, memory, or Windows
internals. Every concept is explained before the code that uses it.

---

## Background: How an OS runs programs

### What a process is

When you double-click an app, Windows doesn't just run the `.exe` file. It
creates a **process** — a container that holds:

- **The program's code** loaded into memory
- **The program's private memory** (variables, heap allocations)
- **File handles** (open files, network connections)
- **Threads** (the actual units of execution — more on these below)
- **A priority level** that tells the CPU scheduler how important this process is

Every process gets a **PID (Process ID)** — a number Windows uses to refer to it.
You can see all running processes in Task Manager.

### What a thread is

A process is a container, but it doesn't run by itself. Inside every process are
one or more **threads** — each thread is an independent sequence of instructions
that the CPU executes. A single-threaded app has one thread doing everything. A
browser like Chrome has dozens: one for the UI, one per tab, one for networking,
one for the GPU, etc.

When we say "the CPU is running a process," what we actually mean is "the CPU is
executing one of that process's threads." A process with 40 threads can do 40
things simultaneously (assuming you have enough CPU cores).

### What CPU% means

The CPU can only execute one thread per core at a time. When you have 200 threads
but only 8 cores, the OS rapidly switches between threads — giving each a tiny
slice of time. This is called **scheduling**.

**CPU%** measures what fraction of available CPU time a process consumed over
a measurement window. 100% on a machine with 8 cores means it used an entire
core's worth of computation. The measurement needs *two points in time* — you
can't know how much CPU was used without knowing the starting state and then
measuring again later. This is why the `top` command waits 0.5 seconds between
two snapshots.

### What priority means

Not all threads are equal. The scheduler gives higher-priority threads more CPU
time and lower-priority threads less. Windows uses a numeric scale:

| Class name | Value | What it means |
|---|---|---|
| Idle | 4 | Only runs when nothing else wants CPU |
| Below Normal | 6 | Runs less often than normal apps |
| Normal | 8 | Default for most apps |
| Above Normal | 10 | Slightly ahead of normal |
| High | 13 | Gets CPU even at the expense of normal apps |
| Realtime | 24 | Dangerous — can starve the OS itself |

psutil exposes these through the concept of "priority class" with values like
`IDLE_PRIORITY_CLASS = 64`, `BELOW_NORMAL_PRIORITY_CLASS = 16384`, etc. These are
different numbers but map onto the same scheduler levels above.

Lowering priority doesn't stop a process from running. It just tells the
scheduler "when you have to choose, give CPU to other things first." A Chrome
window you're actively using stays at Normal; a background updater at Below Normal
gets whatever CPU is left over.

### What suspend means

Every thread in a process can be individually "suspended" — frozen mid-execution.
The CPU stops executing it, and the OS won't give it any time until someone
resumes it. A suspended process:

- Uses **zero CPU** (the scheduler skips it entirely)
- Keeps **all its memory** (nothing is freed or moved to disk)
- Keeps **all its open files and sockets** (no data is lost, connections stay open)
- **Doesn't know it was suspended** — when resumed, it continues from exactly
  where it was, as if no time had passed

This is different from killing a process. The process is still there, alive,
just paused.

---

## Background: Windows memory model

### Physical vs virtual memory

Your PC has a fixed amount of physical RAM (e.g. 16 GB). But programs don't
directly address physical RAM — they address **virtual memory**. Each process
gets its own private virtual address space (on 64-bit Windows, this is
theoretically 128 TB per process).

The OS maintains a **page table** that maps each virtual address to a physical
address. A page is typically 4 KB. When a process accesses a virtual address,
the CPU looks it up in the page table and reads the physical memory at the
mapped location.

### What "paging" means

The OS can take a memory page that hasn't been used recently, write it to a file
on disk (the **page file**), and free that physical RAM for something else. The
page table marks that page as "not in memory." When the process tries to access
it again, the CPU triggers a **page fault** — the OS reads the page back from disk
and resumes the process.

A **hard page fault** (also called a hard fault) means data had to come from disk.
Disk is thousands of times slower than RAM. A system with frequent hard faults
feels sluggish and unresponsive even if RAM% looks fine.

### Why RAM% is a misleading signal

Windows deliberately fills all available RAM with **disk cache** — recently
read files stored in memory so future reads are instant. This is a feature: it
makes disk operations faster. But it means 85% RAM usage doesn't tell you the
system is struggling. Windows evicts the cache under pressure.

The two real memory pressure signals are:

**Commit ratio** — the ratio of `CommitTotal / CommitLimit`. When a process asks
the OS to allocate memory (even if it hasn't used it yet), the OS "commits" that
space — it promises to provide it. `CommitLimit` is the total it can promise
(physical RAM + page file size). When this ratio approaches 1.0, the OS can't
make new commitments. Programs start failing to allocate memory. Crashes follow.

**Hard faults per second** — directly measures how often the OS had to read a
page from disk. Even 5/second is noticeable as stuttering. 50/second is severe.

---

## Background: Windows-specific concepts used in this project

### What DLLs are

A DLL (Dynamic-Link Library) is a file containing functions that multiple programs
can share. `kernel32.dll` contains core Windows functions (`OpenProcess`,
`TerminateProcess`, `CloseHandle`). `user32.dll` contains UI functions
(`GetForegroundWindow`, `EnumWindows`, `PostMessageW`). `psapi.dll` contains
process and memory query functions. `pdh.dll` contains performance counter APIs.

These are Windows's public API — how any program talks to the operating system
for anything beyond basic computation.

### What ctypes is

Python can call C functions in DLLs directly using `ctypes`, the standard library
module for foreign function interface. You tell it:
1. Where the function lives (`ctypes.WinDLL("kernel32")`)
2. What types its arguments are (`.argtypes`)
3. What type it returns (`.restype`)

Then you call it like a normal Python function and ctypes handles the translation
between Python objects and raw C memory.

This project uses ctypes to call Windows APIs that psutil doesn't expose: commit
ratio (`GetPerformanceInfo`), performance counters (`PdhOpenQueryW` etc.), window
enumeration (`EnumWindows`), and Efficiency Mode (`SetProcessInformation`).

### What psutil is

psutil is a Python library that wraps the most common OS process queries in a
cross-platform API. Instead of writing ctypes code to read process memory usage,
you call `psutil.Process(pid).memory_info()` and get back a Python object.

It handles the cross-platform differences (Linux reads `/proc/pid/status`; Windows
calls `NtQuerySystemInformation`) so you write one piece of Python instead of two
platform-specific C-style implementations.

This project uses psutil for: listing all processes, getting memory info, CPU
usage, thread count, process priority (nice value), suspend/resume/terminate,
iterating services, and disk I/O counters.

### What PDH is

PDH (Performance Data Helper) is a Windows API for reading the same performance
counters you see in Resource Monitor (`\Memory\Pages Input/sec`,
`\Processor\% Processor Time`, etc.). You open a "query," add "counters" to
monitor, then collect data at intervals. Rate counters (like pages/sec) need two
collections to compute: the first establishes a baseline, the second measures the
change over time.

This project uses PDH for the hard faults counter because psutil doesn't expose it
and the raw kernel struct for `GetPerformanceInfo` only gives total counts, not
a computed rate.

### What the Windows Registry is

The Registry is a hierarchical database built into Windows that stores
configuration for the OS and installed applications. It has "hives" (top-level
sections):

- `HKEY_CURRENT_USER (HKCU)` — settings for the currently logged-in user
- `HKEY_LOCAL_MACHINE (HKLM)` — system-wide settings

The key `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` contains a list of
programs that launch automatically when the current user logs in. Each entry is
a name → command string pair (e.g. `"Discord" → "C:\Users\...\Discord.exe --start-minimized"`).

This project reads three Run keys to detect startup programs.

### What services are

A Windows **service** is a special kind of background process managed by the
**Service Control Manager (SCM)**. Services can start before any user logs in,
run as system accounts (not as you), and be stopped/started independently. They
include things like the Print Spooler, Windows Update, and third-party antivirus
engines.

This project enumerates service PIDs (slow, ~1 second) to identify processes
that should be treated with extra caution — they are managed by the OS
infrastructure, not by the user.

### What Authenticode signatures are

Windows has a system called **Authenticode** where software publishers can
cryptographically sign their executables. The signature proves:
1. The file came from that publisher (they hold the private key)
2. The file hasn't been modified since signing (the hash is embedded)

When you inspect `chrome.exe`, the system can verify that Google LLC signed it
and the file is intact. An unsigned or invalidly-signed exe is more suspicious.

This project calls PowerShell's `Get-AuthenticodeSignature` — a high-level
wrapper around the Win32 Authenticode APIs — to extract the signing organisation.

### What Efficiency Mode is

Windows 11 added "Efficiency Mode" to Task Manager. When you enable it for a
process, it gets a leaf icon and the OS treats it as low-priority work. Under the
hood, two things happen simultaneously:

1. **Priority is set to Idle** — the scheduler barely gives it CPU time
2. **EcoQoS flag is set** via `SetProcessInformation(ProcessPowerThrottling)` —
   this tells Windows to also throttle the process's power consumption, boost it
   less aggressively, and generally treat it as "background work"

Both must be set together for the leaf icon to appear and for the full effect to
kick in. Setting only priority or only EcoQoS gives partial results.

---

## How the code is organised

```
win-optimizer/
├── pyproject.toml              — package config, dependencies
├── data/
│   ├── known_processes.json    — curated descriptions of common processes
│   └── journal.db              — created at runtime, stores action history
├── optimizer/
│   ├── models.py               — shared data types
│   ├── platform.py             — loads Windows DLLs once at startup
│   ├── journal.py              — SQLite database for action history + undo
│   └── tools/
│       ├── safety.py           — checks that protect the OS from bad actions
│       ├── system.py           — reads whole-PC stress metrics
│       ├── processes.py        — reads the full process list
│       ├── windows.py          — reads window state (what's on screen)
│       ├── startup.py          — reads what launches at login
│       ├── signature.py        — checks who signed an executable
│       ├── knowledge.py        — looks up what a process is known to be
│       ├── actions.py          — the only file that actually changes anything
│       └── __main__.py         — CLI entry point
└── tests/
    ├── fakes.py                — fake process data so tests don't need a real PC
    ├── conftest.py             — shared test setup
    └── test_*.py               — 109 tests, 7 skipped (Windows-only)
```

Everything under `tools/` except `actions.py` is **read-only** — it gathers
information but changes nothing. Only `actions.py` mutates process state.
This separation makes it easy to reason about what can cause side effects.

---

## What you can do with it right now

Everything runs through:

```
python -m optimizer.tools <command>
```

### Command 1: See how stressed the PC is

```
python -m optimizer.tools pressure
```

Sample output:

```
CPU:         14.3%
RAM:         67.1%
Commit:      0.61x  (>0.8 = pressure)
Hard faults: 0.0/s
Disk busy:   2.4%
```

**CPU** — percentage of total CPU time used across all cores right now.

**RAM** — percentage of physical memory in use. As explained above, this is often
misleading. 80% is usually fine because Windows fills spare RAM with file cache.

**Commit** — the ratio of reserved virtual memory to total available. This is the
early warning sign for "system is about to struggle." 0.61 means 61% of virtual
memory is reserved. Above 0.8 starts to cause problems. Above 0.95 means programs
may start failing to allocate memory.

**Hard faults** — how many times per second running processes needed to read a
memory page from disk (because it was paged out). Zero is ideal. Anything above
~10/sec is noticeable.

**Disk busy** — an approximation of how saturated the disk is, computed by
measuring how many milliseconds the disk spent doing I/O over the last second,
then expressing that as a percentage of a full second. Not precise but useful
for spotting a disk that's completely saturated.

### Command 2: List the busiest processes

```
python -m optimizer.tools top
python -m optimizer.tools top --by mem
python -m optimizer.tools top -n 20
```

Sample output:

```
    PID    CPU%        MB  NAME
------------------------------------------
   4820    12.4     312.1  chrome.exe
   9044     8.1      89.3  code.exe
   1532     3.2     210.4  msedge.exe
```

`PID` is the process ID. `MB` is private memory — the memory that belongs only
to this process (not shared with other processes, not disk cache, just the app's
own allocations). This is the meaningful number for "how much RAM does this app
actually use."

The command runs two scans internally with a 0.5-second gap. The gap is necessary
because CPU% is a measurement of *change* — you need to observe the process at two
points in time to know how much CPU it used between them. Without the gap, every
process would show 0%.

### Command 3: Inspect one process in detail

First run `top` to get a PID, then:

```
python -m optimizer.tools inspect 4820
```

Sample output:

```
PID:        4820
Name:       chrome.exe
Exe:        C:\Program Files\Google\Chrome\Application\chrome.exe
User:       DESKTOP\arnav
Parent:     explorer.exe (ppid 5612)
Uptime:     3847s
CPU:        12.4%
Private MB: 312.1
Threads:    42
Priority:   32
[Known]     user_app: Google Chrome browser. Each tab and extension is a separate process.
[Signed by] Google LLC
```

**Parent** — who launched this process. Every process is created by another
process. `explorer.exe` is the Windows shell (desktop + taskbar), so apps you
launch by clicking are children of explorer. Services are children of
`services.exe`.

**Priority 32** — this is psutil's internal representation for Normal priority.
The actual scheduler level is "Normal."

**[Known]** — looked up from `data/known_processes.json`. The file contains
descriptions of ~25 common processes written in plain language.

**[Signed by Google LLC]** — the result of running PowerShell's
`Get-AuthenticodeSignature` on the exe file and extracting the `O=` (organisation)
field from the certificate.

If the tool detects a protected system process name (like `svchost.exe`) running
from outside `C:\Windows\`, it prints a `[WARNING]` line. This is a common
malware technique — name your malicious process after a critical system process
to make it look legitimate.

### Command 4: Act on a process

First get the PID from `top`, then:

```
python -m optimizer.tools act 4820 lower
python -m optimizer.tools act 4820 efficiency
python -m optimizer.tools act 4820 suspend
python -m optimizer.tools act 4820 close
python -m optimizer.tools act 4820 terminate
```

Add `--dry-run` to check safety without actually doing anything:

```
python -m optimizer.tools act 4820 efficiency --dry-run
```

```
[DRY RUN] dry run
  undo info: {'fn': 'restore_efficiency_mode', 'priority': 32}
```

The five actions in order from gentlest to most severe:

**`lower`** — sets the process priority to Below Normal. The process keeps
running and doing its work, but the CPU scheduler will always prefer other
normal-priority processes over it. Good for background apps that don't need
to be responsive. Fully reversible.

**`efficiency`** — enables Windows Efficiency Mode. Sets priority to Idle (even
lower than Below Normal) and activates the EcoQoS power throttling flag. The leaf
icon appears in Task Manager. The process barely gets any CPU and Windows deprioritises
it for power budgeting too. Fully reversible.

**`suspend`** — freezes all threads in the process instantly. The process uses
zero CPU. Its memory stays allocated. Its files and network connections stay open.
It is completely unaware time has passed. When resumed, it continues from exactly
where it stopped. Reversible (use `resume` or let the journal auto-resume it).

**`close`** — sends a `WM_CLOSE` message to each of the process's visible windows.
This is exactly what happens when you click the X button. The app receives the
message and can choose to save files, show a "are you sure?" dialog, or close
immediately. If the app has no windows (a background service), this command
fails — there's nothing to close. Not reversible (the app is gone, but the user
can reopen it).

**`terminate`** — calls `TerminateProcess` on Windows. This is an immediate,
unconditional kill. The OS removes the process from memory instantly, no questions
asked, no callbacks, no saving. Data not yet written to disk is lost. This is the
last resort.

---

## Key decisions and why they were made

### Why every action takes a `ProcessRef` instead of just a PID

Windows **reuses PIDs**. When a process exits, its PID number goes back into a
pool and the next new process might get the same number. If you scan processes at
time T and then act on PID 4820 at time T+2, that PID might now belong to a
completely different program.

Every action takes a `ProcessRef` which bundles:
- `pid` — the process ID
- `create_time` — a high-resolution timestamp of when this process was started
- `name` — the executable name
- `exe` — the full path to the executable

Before every action, the code re-reads the process at that PID and checks all
four fields. If `create_time` changed, the PID was reused — the action is refused.
This makes it impossible to accidentally act on the wrong process.

### Why safety checks run inside every action, not just in the CLI

The CLI does check safety before presenting options. But the action functions
(`lower_priority`, `set_efficiency_mode`, etc.) also check themselves, every time,
regardless.

The reason: the future agent layer (an LLM deciding what to do) will call these
functions directly. LLMs can make mistakes, hallucinate, or misunderstand which
processes are safe to touch. If the safety logic lived only in the caller, one
confused agent call could trigger `terminate` on `csrss.exe` — which causes an
immediate blue screen.

The protected list includes names like `csrss.exe` (Client/Server Runtime —
terminating it causes an instant BSOD), `lsass.exe` (Local Security Authority —
handles login, terminating it causes logout/BSOD), `dwm.exe` (Desktop Window
Manager — the entire visual desktop goes black), and ~15 others.

It also protects processes running as service accounts (`NT AUTHORITY\SYSTEM`),
the optimizer's own process, and the optimizer's parent process (the terminal
you're running it from).

### Why Commit ratio is more reliable than RAM%

When a program calls `malloc()` or creates a Python list, the OS doesn't
immediately assign physical RAM. It makes a **commit** — a promise to provide that
memory when it's actually accessed. `CommitTotal` is the total of all outstanding
promises. `CommitLimit` is the maximum the OS can promise (RAM + page file).

When `CommitTotal / CommitLimit` approaches 1.0, the OS can't make new promises.
Programs start getting `NULL` back from `malloc()` and crashing. This is real
memory pressure.

RAM% just measures physical RAM use. Windows will happily show 85% RAM use when
the system is completely healthy, because 30% of that is disk cache that can be
evicted instantly.

### Why PDH needs two samples and why that requires a persistent class

The `\Memory\Pages Input/sec` counter is a **rate counter** — it measures events
per second. To compute "how many per second," the OS needs to see two readings
and divide by the time between them. The first sample establishes a baseline
(count = X at time T). The second sample computes the rate: (Y - X) / (T2 - T1).

This is baked into the PDH API — the first call to `PdhCollectQueryData` and
`PdhGetFormattedCounterValue` after opening a query gives `PDH_CSTATUS_INVALID_DATA`.
Only the second call gives a real value.

The `_HardFaultSampler` class keeps the PDH query handle alive. Its constructor
makes the first (baseline) collection at module import time. Every call to
`get_system_pressure()` makes the second collection and gets the computed rate.
If you closed the query and re-opened it on every call, you'd always get the first
sample and never get a value.

### Why there's a process object cache for cpu_percent

`psutil.cpu_percent(interval=None)` works by measuring CPU time used since the
last time you called it on **that specific Process object**. It stores the
previous measurement inside the object.

`psutil.process_iter()` creates a new `Process` object for every process on every
call. New objects have no previous measurement, so `cpu_percent` returns 0 for
all of them on the first call.

`_proc_cache` is a dictionary keyed by `(pid, create_time)` that stores the same
Process object across multiple `list_processes()` calls. On the second call, the
cached object has a previous measurement and can compute a real delta. Entries are
removed when a process exits (detected by it no longer appearing in the scan),
so the cache stays lean over time.

### Why the journal writes a row before acting, not after

The sequence for any reversible action is:

1. Write a `pending` row to the database
2. Do the action (lower priority / suspend / etc.)
3. Update the row to `active`

If the program crashes between step 1 and step 3, the `pending` row is still in
the database. When the optimizer starts up next time, `undo_all()` finds that row
and reverses the action (restores the priority, resumes the process). The process
is never left permanently modified without a record of how to undo it.

If we wrote the row *after* acting, a crash mid-action would leave the process
modified with no record of what was done.

### Why SQLite uses WAL mode

WAL stands for Write-Ahead Logging. It's a different way SQLite structures its
database writes.

In default mode, writing to a database involves modifying the file in place. If
power cuts out mid-write, the file can be left in a corrupt, half-written state.

In WAL mode, writes go to a separate "write-ahead log" file first. The main
database file is only modified once the write is confirmed complete. If power
cuts during a write, the main database is untouched and the incomplete log entry
is just discarded on next open. The result: the database is never corrupt.

### Why `journal.py` imports `actions.py` inside a function, not at the top

Python modules are loaded once and cached. When you do `import X`, Python runs X's
code. If X tries to `import Y` while being loaded, Python loads Y. If Y tries to
`import X`, Python finds X is already being loaded (but not finished) and gives Y
an incomplete version of X. This is a **circular import error**.

`actions.py` needs `journal.py` (to record every action it takes).
`journal.py` needs `actions.py` (to call `restore_priority` and `resume` during
undo).

The fix: `journal.py` does the import *inside* the `undo()` function body:

```python
def undo(entry):
    from optimizer.tools import actions  # imported here, not at the top
    ...
```

By the time `undo()` is actually called at runtime, both modules have long since
finished loading. The circular dependency only matters during the loading phase,
not during execution.

### Why tests use a FakeProcessProvider instead of mocks

Most testing of code that touches external systems uses "mocking" — replacing
real functions with fake ones at runtime. Python's `unittest.mock.patch` does
this. The problem: it patches by *name*. If you patch `optimizer.tools.actions.psutil.Process`,
the patch breaks silently the moment you rename anything in that path.

Instead, every action tool accepts an optional `provider=` argument. In production
it's `None` (use real psutil). In tests, you pass a `FakeProcessProvider`. The
fake stores a list of fake processes and records every mutating call in `self.calls`.

This approach is called **dependency injection**. The dependency (the thing that
talks to the real OS) is injected from outside rather than hardcoded inside. Tests
inject a fake; production uses the real thing. The fake must implement the exact
same interface, and if the interface changes, the fake breaks loudly — no silent
failures.

### Why `_UNDOABLE_ACTIONS` prevents an infinite undo loop

When you lower a process's priority, the journal records a `lower_priority` entry
with status `active`. When undo is called, it calls `restore_priority`, which
records a `restore_priority` entry with status `done`.

If `undo_all()` (which runs on startup) searched for *all* journal entries to
undo, it would find the `restore_priority` entry and try to undo that too — by
calling `lower_priority` again — which would create another entry to undo, forever.

The constant `_UNDOABLE_ACTIONS = ("lower_priority", "set_efficiency_mode", "suspend")`
explicitly lists only the original actions. `restore_priority` and `resume` are
not in this list, so `undo_all()` never tries to reverse them.

### Why the signature check spawns PowerShell instead of calling Win32 directly

Verifying an Authenticode signature using the raw Win32 API requires calling:
`WinVerifyTrust`, `CryptQueryObject`, `CryptMsgGetParam`, `CertGetNameString`,
and iterating certificate chains — roughly 100 lines of ctypes declarations and
pointer manipulation.

PowerShell's `Get-AuthenticodeSignature` wraps all of this in one command that
returns JSON. The tradeoff is speed: spawning PowerShell takes about 1 second.
The cache (keyed by file path + file modification time) means each binary is only
checked once. If the exe file is rebuilt (modification time changes), the cached
result is discarded and the check runs again.

`CREATE_NO_WINDOW` is a Windows process creation flag that prevents a console
window from briefly flashing on screen when the PowerShell process starts.

### Why `known_processes.json` has a `path_hint` field

Two completely different programs can ship an executable with the same filename.
Google ships `updater.exe`. So might a dozen other vendors. A lookup by name alone
would return the wrong entry.

`path_hint` is a substring that must be present in the full exe path for a match
to count. Google's entry has `"path_hint": "Google"` — it only matches
`updater.exe` if the path contains the word "Google"
(e.g. `C:\Program Files\Google\Update\updater.exe`). A generic fallback entry
has `"path_hint": ""` which matches anything.

The list is checked in order — specific entries (with a path_hint) come first.
The first match wins.

---

## What's not built yet

The tools layer is complete. These remain for future phases:

**Agent layer** — scanner, analyst, and executor agents. The scanner calls the
read-only tools and assembles a picture of system state. The analyst (an LLM)
decides what actions to recommend. The executor (with user approval) calls the
action tools.

**LLM integration** — Ollama running a local model that the analyst agent uses.
The tools layer is designed so every tool's output is structured data — the LLM
never reads raw text, it reads typed Python objects that the tools guarantee are
accurate.

**UI** — a tkinter popup that shows the analyst's recommendations and asks the
user to approve or reject each one.

**Always-on loop** — a background thread that calls `get_system_pressure()` every
few seconds, and when pressure stays high, triggers the agent pipeline.

**Task Scheduler integration** — registers the monitor to start automatically
when the user logs in, without needing to keep a terminal window open.
