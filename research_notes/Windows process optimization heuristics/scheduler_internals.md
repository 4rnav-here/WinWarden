# Windows Process Scheduler Internals

## Priority Classes and the 0–31 Thread Priority Scale

### Takeaway
Windows has 6 process priority classes that define a base priority range for their threads. Thread priority level offsets combine with the class to yield a final base priority on a 0–31 integer scale, where 0–15 is the "dynamic" (variable) range and 16–31 is the "realtime" range.

### Cited Findings
- Priority levels range from 0 (lowest) to 31 (highest); only the zero-page thread (memory manager) may run at 0. The practical application range is 1–31. — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- The 6 priority classes are: `IDLE_PRIORITY_CLASS`, `BELOW_NORMAL_PRIORITY_CLASS`, `NORMAL_PRIORITY_CLASS`, `ABOVE_NORMAL_PRIORITY_CLASS`, `HIGH_PRIORITY_CLASS`, `REALTIME_PRIORITY_CLASS`. — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- Within each class, 7 thread priority levels exist: `THREAD_PRIORITY_IDLE`, `THREAD_PRIORITY_LOWEST`, `THREAD_PRIORITY_BELOW_NORMAL`, `THREAD_PRIORITY_NORMAL`, `THREAD_PRIORITY_ABOVE_NORMAL`, `THREAD_PRIORITY_HIGHEST`, `THREAD_PRIORITY_TIME_CRITICAL`. — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- Complete base priority table (process class × thread level → numeric priority):

  | Process Class | IDLE | LOWEST | BELOW_NORMAL | NORMAL | ABOVE_NORMAL | HIGHEST | TIME_CRITICAL |
  |---|---|---|---|---|---|---|---|
  | IDLE | 1 | 2 | 3 | **4** | 5 | 6 | 15 |
  | BELOW_NORMAL | 1 | 4 | 5 | **6** | 7 | 8 | 15 |
  | NORMAL | 1 | 6 | 7 | **8** | 9 | 10 | 15 |
  | ABOVE_NORMAL | 1 | 8 | 9 | **10** | 11 | 12 | 15 |
  | HIGH | 1 | 11 | 12 | **13** | 14 | 15 | 15 |
  | REALTIME | 16 | 22 | 23 | **24** | 25 | 26 | 31 |

  — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- Priorities 0–15 are the "dynamic" range (subject to runtime boosts); priorities 16–31 are the "realtime" range where the scheduler never adjusts priorities or quanta and simply round-robins at the highest runnable level. — [Windows NT processor scheduling, Wikipedia](https://en.wikipedia.org/wiki/Windows_NT_processor_scheduling)
- `THREAD_PRIORITY_IDLE` always maps to priority 1 regardless of class (except REALTIME where it maps to 16). `THREAD_PRIORITY_TIME_CRITICAL` always maps to 15 (except REALTIME where it maps to 31). — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- The scheduler treats all threads of the same priority as equal and round-robins among them. When a higher-priority thread becomes runnable, the lower-priority thread is preempted immediately without completing its quantum. — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- Confirmed process class base priorities (THREAD_PRIORITY_NORMAL): Idle=4, Below Normal=6, Normal=8, Above Normal=10, High=13, Realtime=24. — [Thread Priorities in Windows – Pavel Yosifovich](https://scorpiosoftware.net/2023/07/14/thread-priorities-in-windows/)

### Inferences
- The gap between HIGH (13) and REALTIME (24) at normal thread level is deliberately large; this makes it difficult to accidentally preempt OS threads with user-mode code.
- The fact that `TIME_CRITICAL` in all non-REALTIME classes caps at 15 (the dynamic/realtime boundary) prevents user-mode processes from accidentally entering the realtime scheduling band.

### Gaps
- None; the MSDN table provides exact numeric values for all combinations.

---

## Foreground Boost Mechanism

### Takeaway
When a process window comes to the foreground, Windows boosts both its priority class and its threads' quantum allocation. The boost is controlled by the `Win32PrioritySeparation` registry value and decays by one priority level per completed quantum until reaching the thread's base priority.

### Cited Findings
- When a `NORMAL_PRIORITY_CLASS` process becomes the foreground window, the scheduler boosts its priority class so it is greater than or equal to any background process's priority class. The priority class returns to its original setting when the process leaves the foreground. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- The foreground process also receives a **quantum boost**: threads in the foreground window process have their quantum targets tripled. This means the foreground application is interrupted less often and can complete more work per scheduling cycle. — [BSODTutorials: Thread Quantum, Thread Priority Boosting](http://bsodtutorials.blogspot.com/2013/11/thread-quantum-thread-priority-boosting.html)
- The foreground boost level is one of three settings packed into `Win32PrioritySeparation` (bits 0–1), with values ranging 0–3. The Windows client default resolves to boost level 2. — [Win32PrioritySeparation, JinshiTweaks](https://jinshitweaks.com/reference/win32priorityseparation/)
- `Win32PrioritySeparation` is a DWORD at `HKLM\SYSTEM\CurrentControlSet\Control\PriorityControl\Win32PrioritySeparation` packing three scheduling decisions into 6 bits: bits 4–5 (quantum length: short vs long), bits 2–3 (quantum variability: variable vs fixed), bits 0–1 (foreground boost level 0–3). — [Win32PrioritySeparation, JinshiTweaks](https://jinshitweaks.com/reference/win32priorityseparation/)
- The Windows client default value for `Win32PrioritySeparation` is `0x02`, which resolves to: short quantums, variable quantums, foreground boost level 2. — [Win32PrioritySeparation, JinshiTweaks](https://jinshitweaks.com/reference/win32priorityseparation/)
- Common registry values and their effects:
  - `0x26`: Short, variable quantums, boost level 2 (effectively same as client default with explicit settings)
  - `0x18`: Long, fixed quantums, no foreground boost
  - `0x2A`: Short, fixed quantums, high foreground boost
  - `0x1A`: Long, fixed quantums, high foreground boost
  — [Recovery Monkey: Processor scheduling and quanta in Windows](https://recoverymonkey.org/2007/08/17/processor-scheduling-and-quanta-in-windows-and-a-bit-about-unixlinux/)
- After raising a thread's dynamic priority, the scheduler reduces that priority by **one level per completed time slice** until the thread drops back to its base priority. A thread's dynamic priority is never less than its base priority. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- Only threads with base priority 0–15 receive dynamic priority boosts; threads with base priority 16–31 (realtime) are never boosted. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- When a window receives input (timer messages, mouse messages, keyboard input), the scheduler boosts the priority of the owning thread. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- Priority boost can be disabled per-process or per-thread via `SetProcessPriorityBoost` / `SetThreadPriorityBoost`; queried via `GetProcessPriorityBoost` / `GetThreadPriorityBoost`. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)

### Inferences
- The foreground quantum tripling is separate from the priority-level boost: the foreground process both runs at a higher priority AND gets 3× more CPU time when it does run.
- The "boost level 2" default means the foreground process class is raised by 2 levels relative to background, ensuring interactive responsiveness without completely starving background tasks.

### Gaps
- Exact numeric millisecond value of the priority-class boost (how many priority levels the class is raised) is not specified in Microsoft's public documentation; the Win32PrioritySeparation bits 0–1 indicate a relative boost level (0–3) without mapping to explicit numeric class changes.

---

## Thread Quantum Mechanics

### Takeaway
A thread quantum is the maximum CPU time a thread may run before the scheduler can switch to another thread of equal priority. On Windows client editions, quantums are short and variable, with foreground threads receiving a 3× quantum multiplier; Windows Server uses long, fixed, equal quantums for all threads.

### Cited Findings
- A thread quantum is approximately 2 clock intervals governed by the HAL (Hardware Abstraction Layer). — [BSODTutorials: Thread Quantum](http://bsodtutorials.blogspot.com/2013/11/thread-quantum-thread-priority-boosting.html)
- On Windows Workstation (Vista/XP/2000 Pro and Windows 10/11 client): variable quantum, typically 20–60ms range, with background processes always receiving the smallest possible quantum. — [Recovery Monkey: Processor scheduling and quanta in Windows](https://recoverymonkey.org/2007/08/17/processor-scheduling-and-quanta-in-windows-and-a-bit-about-unixlinux/)
- On Windows Server editions: fixed 120ms quantum for all processes uniformly, regardless of foreground/background status. — [Recovery Monkey: Processor scheduling and quanta in Windows](https://recoverymonkey.org/2007/08/17/processor-scheduling-and-quanta-in-windows-and-a-bit-about-unixlinux/)
- Foreground processes receive a **quantum boost that triples their quantum target** relative to background processes. — [BSODTutorials: Thread Quantum](http://bsodtutorials.blogspot.com/2013/11/thread-quantum-thread-priority-boosting.html)
- Quantum settings (short/long, variable/fixed) are controlled by bits 2–5 of `Win32PrioritySeparation`. Windows client defaults to short + variable. — [Win32PrioritySeparation, JinshiTweaks](https://jinshitweaks.com/reference/win32priorityseparation/)
- If a higher-priority thread becomes runnable, the current thread is preempted immediately, without waiting for its quantum to expire. — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- When a thread voluntarily yields (blocks on I/O, calls Sleep, waits on a synchronization object), any remaining quantum time is typically forfeited. The scheduler then picks the next highest-priority runnable thread. — [Thread scheduling (ctd): quanta and switching, Javamex](https://www.javamex.com/tutorials/threads/thread_scheduling_2.shtml)
- Calls to `timeBeginPeriod(1)` by any application reduce the system timer resolution to ~1ms, which also changes the granularity of thread quanta across the system. — BSODTutorials (general note on clock resolution)

### Inferences
- The short + variable client default is optimized for desktop interactivity: short quanta mean the UI stays responsive even when background processes are runnable; variable quanta allow the foreground app to receive longer slices.
- The server fixed-long quantum setting avoids the overhead of frequent context switches and prioritizes throughput over latency.

### Gaps
- The exact clock-tick counts for "short" vs "long" quantum on modern Windows 10/11 are not in public documentation (Windows Internals book reports approximately 2 clock ticks = ~15–20ms for short, ~6 ticks = ~45–60ms for long on client); these values have not been independently confirmed from a primary source in this research session.

---

## Priority Inversion and Priority Inheritance

### Takeaway
Windows uses a mechanism called **AutoBoost** to address priority inversion: when a low-priority thread holds a resource that a higher-priority thread is waiting for, the owner thread's priority is temporarily raised to a floor matching the highest-priority waiter's priority, until the resource is released.

### Cited Findings
- Priority inversion occurs when a high-priority thread (T3, priority 12) is blocked on a resource held by a low-priority thread (T1, priority 4) that is in turn preempted by a medium-priority thread (T2, priority 8). T2 effectively prevents T3 from making progress. — [Priority Inversion, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-inversion)
- Windows addresses priority inversion through **AutoBoost**: it automatically tracks resource reservations and adjusts thread priorities by applying **priority floors** — minimums a thread must never drop below while it holds a resource with high-priority waiters. — [Priority Inversion, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-inversion)
- Specifically: if a low-priority thread acquires a critical section and a higher-priority thread blocks waiting for it, the owner's priority is raised to the **maximum priority of any waiter** until the resource is released. — [Priority Inversion, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-inversion)
- Priority inheritance is well-established in OS literature: the priority inheritance protocol increases a lock holder's priority to the maximum priority of any thread waiting for any resource that holder owns. — [Priority Inheritance, ScienceDirect](https://www.sciencedirect.com/topics/computer-science/priority-inheritance)
- Note: Priority inheritance does not eliminate priority inversion; it minimizes its effect in many situations but cannot guarantee avoidance in all cases. — [Solutions to Priority Inversion, OpenSourceForU](https://www.opensourceforu.com/2019/08/solutions-to-priority-inversion-in-a-multi-threaded-programming-environment/)

### Inferences
- AutoBoost applies specifically to kernel synchronization primitives (critical sections, mutexes) that track ownership. Spin locks, which don't track ownership, cannot use AutoBoost.
- The "priority floor" terminology suggests this is not a temporary boost that decays over quanta (as with IO/input boosts), but rather a hard minimum that holds for the entire duration of lock ownership.

### Gaps
- The specific kernel objects to which AutoBoost applies (e.g., whether it applies to Executive Resource objects, Pushlocks, or only CRITICAL_SECTION/KMUTEX) are documented in Windows Internals (7th ed., Chapter 4) but not in public Win32 API docs; not confirmed from a primary source in this session.

---

## Dynamic Priority Boosting

### Takeaway
Windows automatically applies temporary dynamic priority boosts to threads in response to specific events (I/O completion, window input, foreground transition, starvation). These boosts decay by one level per completed quantum until the thread returns to its base priority.

### Cited Findings
- Three categories of automatic dynamic priority boost: (1) foreground process window activation, (2) window receiving input (timer, mouse, keyboard messages), (3) satisfied wait condition (e.g., disk or keyboard I/O completion). — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- After boosting, the scheduler reduces dynamic priority by **1 level per completed time slice** until returning to base priority. The dynamic priority never falls below the base. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- Only threads with base priority **0–15** receive dynamic boosts; **realtime threads (16–31) are never boosted**. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- GUI thread completing a `KeSetEvent` receives a boost of **+2** to current priority level. — [BSODTutorials: Thread Quantum and Priority Boosting](http://bsodtutorials.blogspot.com/2013/11/thread-quantum-thread-priority-boosting.html)
- Threads waiting on Events or Semaphores receive a boost of **+1** to base priority. — [BSODTutorials: Thread Quantum and Priority Boosting](http://bsodtutorials.blogspot.com/2013/11/thread-quantum-thread-priority-boosting.html)
- Executive Resources (e.g., ERESOURCE): the owner thread's base priority is raised to **14**. — [BSODTutorials: Thread Quantum and Priority Boosting](http://bsodtutorials.blogspot.com/2013/11/thread-quantum-thread-priority-boosting.html)
- **Starvation prevention**: The Balance Set Manager boosts the current priority of threads that have not executed within **4 seconds** to priority **15**, affecting up to 10 threads at a time. — [BSODTutorials: Thread Quantum and Priority Boosting](http://bsodtutorials.blogspot.com/2013/11/thread-quantum-thread-priority-boosting.html)
- Priority boosting can be disabled per-process or per-thread via `SetProcessPriorityBoost` and `SetThreadPriorityBoost`. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- Boost decay is "staggered": IO completion effectively gives a thread extra quanta at an elevated priority because the priority decays by 1 after each quantum, so a +3 boost lasts for 3 quanta before returning to base. — [Understanding Windows CPU Scheduling, Medium/@_dev_null](https://medium.com/@_dev_null/understanding-windows-cpu-scheduling-de2d709a5b28)

### Inferences
- The staggered decay means that a thread completing a high-latency I/O gets more than one quantum at elevated priority; the effective scheduling benefit is proportional to the boost magnitude.
- The starvation-prevention boost to priority 15 (just below realtime) is intentionally aggressive: it guarantees even a completely neglected low-priority thread will eventually run.

### Gaps
- Specific boost magnitudes for keyboard input, mouse input, disk I/O, and network I/O completions (often cited as +6, +4, +1 in third-party sources) are not confirmed in primary Microsoft documentation; BSODTutorials provides some values but this is not a primary Microsoft source.

---

## Base Priority vs. Current (Dynamic) Priority

### Takeaway
Every thread has a **base priority** (derived from process class + thread level offset) and a **current (dynamic) priority** (what the scheduler actually uses). The dynamic priority starts equal to the base but can be temporarily raised by boosts; it never drops below the base.

### Cited Findings
- "Each thread has a dynamic priority. This is the priority the scheduler uses to determine which thread to execute. Initially, a thread's dynamic priority is the same as its base priority." — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- The base priority is determined by: process priority class × thread priority level offset (see the table in the first section). — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
- "The system can boost and lower the dynamic priority, to ensure that it is responsive and that no threads are starved for processor time." A thread's dynamic priority is **never less than its base priority**. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- Process Explorer (Sysinternals) exposes both the base priority and the current dynamic priority in separate columns for each thread, allowing observation of boosts in real time. — [Thread Priorities in Windows – Pavel Yosifovich](https://scorpiosoftware.net/2023/07/14/thread-priorities-in-windows/)
- "The dynamic priority is the current thread's priority, which could be slightly higher than the base (temporarily), and is changed because of certain decisions made by the kernel scheduler." — [Thread Priorities in Windows – Pavel Yosifovich](https://scorpiosoftware.net/2023/07/14/thread-priorities-in-windows/)
- `GetThreadPriority` returns the thread's priority level relative to its process class (i.e., the offset), not the absolute numeric base priority. — [Scheduling Priorities, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)

### Inferences
- Because `GetThreadPriority` returns a relative offset, a process optimizer that wants the true numeric base priority must multiply: look up the process class, then apply the table to get the absolute value.
- Transient boosts visible in Process Explorer indicate the thread recently completed an I/O or received input; persistent above-base current priority suggests a lock-based AutoBoost is in effect.

### Gaps
- No gap; this is well-documented in primary sources.

---

## EcoQoS / Efficiency Mode Scheduler Behavior

### Takeaway
EcoQoS (Efficiency Mode) directs Windows to schedule affected threads on energy-efficient CPU cores (E-cores on hybrid processors) at reduced CPU frequencies. Scheduling priority remains the primary dispatch metric; EcoQoS adds a secondary layer that influences core selection and power management without hard-bypassing priority order.

### Cited Findings
- EcoQoS "Always selects most efficient CPU frequency and schedules to efficient cores." It was introduced in Windows 11. — [EcoQoS QoS documentation, MicrosoftDocs/win32](https://github.com/MicrosoftDocs/win32/blob/docs/desktop-src/ProcThread/quality-of-service.md)
- Process-level API: `SetProcessInformation()` with the `PROCESS_POWER_THROTTLING_EXECUTION_SPEED` feature flag. Thread-level API: `SetThreadInformation()` with `THREAD_POWER_THROTTLING_EXECUTION_SPEED`. — [EcoQoS documentation, MicrosoftDocs/win32](https://github.com/MicrosoftDocs/win32/blob/docs/desktop-src/ProcThread/quality-of-service.md)
- "Scheduling priority remains the main metric by which the system determines which thread to schedule next"; EcoQoS influences core selection and processor power management as **secondary factors**. — [EcoQoS documentation, MicrosoftDocs/win32](https://github.com/MicrosoftDocs/win32/blob/docs/desktop-src/ProcThread/quality-of-service.md)
- CPU frequency is reduced to the most efficient setting regardless of AC/battery power state when EcoQoS is active. — [EcoQoS documentation, MicrosoftDocs/win32](https://github.com/MicrosoftDocs/win32/blob/docs/desktop-src/ProcThread/quality-of-service.md)
- Task Manager's Efficiency Mode applies both EcoQoS **and** sets the process priority to `IDLE_PRIORITY_CLASS` (Low priority), combining two separate mechanisms. — [Windows Latest: Efficiency Mode details](https://www.windowslatest.com/2022/02/22/interesting-details-of-windows-11s-performance-feature-efficiency-mode-revealed/)
- Microsoft's testing showed up to **90% reduction in CPU power consumption** for EcoQoS-tagged processes, with 14–76% improvement in UI responsiveness of other processes. — [Windows Latest: Efficiency Mode details](https://www.windowslatest.com/2022/02/22/interesting-details-of-windows-11s-performance-feature-efficiency-mode-revealed/)
- On hybrid processors (Intel 12th gen+, AMD Ryzen with E/P cores), EcoQoS processes are preferentially dispatched to E-cores, freeing P-cores for latency-sensitive foreground work. — [EcoQoS gives Windows 11 apps better battery life, TechRepublic](https://www.techrepublic.com/article/ecoqos-gives-windows-11-apps-better-battery-life/)
- The Windows Thread Scheduler is the kernel component making core-selection decisions; EcoQoS tags serve as hints to this scheduler component, not hard constraints. — [Understanding Windows Processor Scheduling Settings, KomuraSoft](https://comcomponent.com/en/blog/2026/03/16/003-windows-processor-scheduling-background-services-p-e-cores/)

### Inferences
- EcoQoS can be applied independently of process priority class. An app can be at NORMAL_PRIORITY_CLASS but still tagged with EcoQoS to get E-core preference and reduced frequency, without being deprioritized relative to other NORMAL threads on P-cores.
- Task Manager's "Efficiency Mode" is a composite: it stacks EcoQoS + Low priority, making it more aggressive than simply applying EcoQoS via the API. A developer using the API directly has finer control.

### Gaps
- The internal kernel structures or data fields that encode the EcoQoS hint per-thread are not documented publicly; how the scheduler's core-selection logic reads this hint is not described in Win32 API docs.
- Behavior on non-hybrid (homogeneous) processors when EcoQoS is applied is not fully documented; presumably only the frequency reduction applies.

---

## CPU-Bound vs. I/O-Bound Process Treatment

### Takeaway
Windows does not explicitly label processes as CPU-bound or I/O-bound, but the dynamic priority boost mechanism naturally advantages I/O-bound threads: they frequently yield the CPU (blocking on I/O), and when their I/O completes they receive a priority boost that moves them ahead of CPU-bound threads consuming full quanta.

### Cited Findings
- When a thread's wait condition (including I/O completion) is satisfied, the scheduler boosts the thread's dynamic priority. — [Priority Boosts, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/priority-boosts)
- I/O-bound threads "voluntarily yield before using their full quantum because those threads are often interactive or I/O bound"; Windows temporarily boosts threads that block before exhausting their quantum. — [Process/Thread Scheduling, LUC OS textbook](https://os.cs.luc.edu/scheduling.html)
- CPU-bound threads tend to use their full quantum each scheduling cycle; I/O-bound threads tend to consume only a fraction of their quantum before blocking. The scheduler observes this pattern implicitly through quantum exhaustion vs. voluntary yields. — [CPU-Bound vs I/O-Bound, DevsUnite](https://devsunite.com/resources/core-subjects/operating-systems/cpu-bound-vs-io-bound-process)
- There is no explicit Windows API to query whether a process is classified as CPU-bound or I/O-bound; classification is behavioral inference: observing CPU time (high → CPU-bound) vs. wait time / I/O bytes (high → I/O-bound) via performance counters (`\Process(*)\% Processor Time`, `\Process(*)\IO Data Bytes/sec`, `\Thread(*)\% Processor Time`). — (general OS scheduling literature, consistent across sources)
- I/O-bound processes are generally assigned higher scheduling priority in theory because their short CPU bursts allow the CPU to be freed for other work; the Windows dynamic boost achieves this implicitly rather than through explicit classification. — [CPU-bound vs I/O-bound, Baeldung CS](https://www.baeldung.com/cs/cpu-io-bound)
- "Past performance is not an indicator of future outcomes": a process that was previously I/O-bound can become CPU-bound; Windows does not permanently label processes. — [Quora: How to find whether a process is I/O bound or CPU bound](https://www.quora.com/How-can-you-find-whether-a-process-is-I-O-bound-or-CPU-bound)

### Inferences
- A process optimizer can infer CPU-bound vs. I/O-bound status by sampling `% Processor Time` vs. `IO Data Operations/sec` from `pdh` / `psutil` over a window of ~1–5 seconds. High CPU% + low IO → CPU-bound; low CPU% + frequent IO → IO-bound.
- CPU-bound processes at the same priority class as I/O-bound processes will be naturally disadvantaged: the I/O-bound processes receive post-completion boosts and get scheduled sooner; the CPU-bound threads only run when the boosted threads have decayed back to base priority.

### Gaps
- The exact boost magnitude applied specifically at disk I/O completion (often cited as +1 in older Windows versions) vs. keyboard/mouse input (+6/+4 in third-party sources) is not confirmed in primary Microsoft documentation for Windows 10/11. The MSDN Priority Boosts page describes the mechanism but not the specific magnitudes per event type.
- Whether Windows 10/11 uses a different set of boost magnitudes than earlier versions (Windows XP/Vista era values are cited in most secondary sources) is not confirmed from a primary source.
