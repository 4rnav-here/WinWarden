# Windows Process Optimization Tool Heuristics

## Process Lasso ProBalance Algorithm — Signals, Triggers, and Actions

### Takeaway
ProBalance monitors for background processes that drive high CPU load, temporarily demotes their priority class to Below Normal, and automatically restores it when the condition passes. Exact numerical thresholds are proprietary and not publicly documented.

### Cited Findings
- ProBalance is described as watching for "background processes monopolizing the CPU" and responding by temporarily lowering their priority class, "typically to Below Normal." — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)
- "Several advanced parameters control if and when ProBalance acts, including the CPU threshold a process must exceed, how long it must exceed it, and what adjustments are applied." These parameters exist and are user-configurable, but no default values are published. — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)
- The throttling action is described as "a marginal, temporary change to the precedence during contention" — the priority adjustment only has effect when there is actual CPU contention. — [ProBalance How It Works, Bitsum](https://bitsum.com/how-probalance-works/)
- By default ProBalance excludes foreground processes, children of the foreground process, non-normal-priority processes, and (optionally) system services. — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)
- An optional integration with Windows Efficiency Mode (EcoQoS) can additionally be applied to restrained processes; this defaults to OFF because it is "more heavy-handed than the stock priority adjustment." — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)
- When ProBalance is actively restraining a process, the system tray icon turns red and the process displays "Restrained" in the Status column; actions are logged. — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)
- The algorithm is described as proprietary; documentation uses phrases like "a little 'market intelligence', some logic, and help from the user." — [ProBalance How It Works, Bitsum](https://bitsum.com/how-probalance-works/)

### Inferences
- The trigger is sustained high CPU usage (not a single-sample spike), since the parameter "how long it must exceed [the threshold]" implies a time window, consistent with avoiding false positives from short bursts.
- The restoration condition is implicit: priority is restored "as soon as the condition passes," meaning ProBalance continuously monitors CPU load and lifts the throttle when the offending process's load drops below the threshold.
- The choice of Below Normal (rather than Idle or Low) is deliberate — it ensures background processes still get CPU time, just yielding to foreground work under contention, minimizing the chance of starving background processes entirely.

### Gaps
- Exact default CPU percentage threshold is not published by Bitsum. Would require running Process Lasso and inspecting the ProBalance settings UI dialog.
- Exact time window (how many seconds/minutes of sustained load triggers action) is not disclosed.
- The mechanism for detecting "condition has passed" (hysteresis, averaging window) is not documented.


## ProBalance Trigger Signal — CPU% vs Sustained Time vs Other

### Takeaway
ProBalance uses both a CPU percentage threshold AND a sustained-time duration as co-triggers; a process must exceed the CPU threshold for a configurable duration before ProBalance acts.

### Cited Findings
- The documentation explicitly states the parameters include "the CPU threshold a process must exceed, [and] how long it must exceed it" — confirming both a CPU% signal and a time window are used. — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)
- ProBalance focuses on "background processes" — the foreground process is excluded by default, making the relevant signal specifically background CPU usage. — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)

### Inferences
- The two-parameter design (threshold + duration) is a classic debouncing pattern — it filters out short CPU bursts (compilation, startup loading) while catching genuinely sustained monopolizers.

### Gaps
- No published sample rate (how often ProBalance polls CPU usage per process).
- Whether it uses per-process CPU% or total system CPU load as the primary signal is not explicitly stated, though the focus on a "background process exceeding its thresholds" implies per-process measurement.


## ProBalance Priority Restoration — How and When

### Takeaway
ProBalance restores a process to its original priority class automatically as soon as CPU load conditions improve; there is no fixed cooldown timer documented.

### Cited Findings
- Adjustments are described as "temporary" and "undone as soon as system conditions change." — [ProBalance Docs, Bitsum](https://bitsum.com/apps/process-lasso/docs/algorithms/probalance/)
- The original priority is always restored; ProBalance explicitly makes "marginal, temporary changes" and never permanently alters priorities. — [ProBalance How It Works, Bitsum](https://bitsum.com/how-probalance-works/)

### Inferences
- "Conditions change" most likely refers to the same threshold/duration check used for triggering — if the process drops below the CPU threshold, the restraint is lifted. A hysteresis band (restore at a lower threshold than the trigger) would be typical engineering practice to prevent oscillation, but is not confirmed.

### Gaps
- No documentation of a hysteresis band or minimum restraint duration.
- No documentation of what happens if a process oscillates rapidly across the threshold (flapping prevention).


## Bitsum Highest Performance Power Plan

### Takeaway
Bitsum Highest Performance (BHP) is a custom Windows power plan (distributed with ParkControl) that disables CPU core parking and frequency scaling to eliminate latency during CPU bursting; it is used by Process Lasso's "Performance Mode" when target applications launch.

### Cited Findings
- BHP "disables CPU core parking and the CPU never drops below its nominal (base) frequency," removing the unpark latency that affects burst workloads. — [Bitsum Highest Performance, Bitsum](https://bitsum.com/bhp/)
- Even the standard Windows High Performance plan still allows some core parking and frequency scaling; BHP removes those remaining constraints. — [ParkControl Release Notes, Bitsum](https://bitsum.com/product-update/parkcontrol-v1-0-3-0-released/)
- Intel Speed Shift (available from 6th-gen Core / Skylake onwards) was cited by Bitsum as validation that low-latency CPU frequency response matters for burst workloads. — [Intel Speed Shift article, Bitsum](https://bitsum.com/product-update/intels-speed-shift-validates-parkcontrol-and-process-lasso/)
- Process Lasso integrates BHP via "Performance Mode": the system switches to BHP automatically when a user-designated application starts, and reverts to a conservative plan via "IdleSaver" during user inactivity. — [Bitsum Highest Performance, Bitsum](https://bitsum.com/bhp/)

### Inferences
- BHP is a power-plan-level optimization complementing ProBalance's priority-level optimization — they operate at different layers (scheduler priority vs. CPU power management).
- The "IdleSaver" companion feature implies Bitsum acknowledges BHP is not suitable as an always-on plan and should be applied only during active use.

### Gaps
- Specific registry/power plan GUID values are not documented in public sources, though ParkControl applies them programmatically.


## Windows 11 Task Manager Efficiency Mode — Automatic vs Manual

### Takeaway
Efficiency Mode in Task Manager is primarily a manual feature; automatic activation is limited to browsers (Edge, Chrome) that apply EcoQoS internally. Windows's automatic background throttling is handled separately by Power Throttling (QoS heuristics), not Task Manager Efficiency Mode.

### Cited Findings
- Efficiency Mode uses the `SetProcessInformation` API with `ProcessPowerThrottling` (EcoQoS): it enforces execution "at the lowest efficient clock speed, scheduling to the most power-efficient cores on heterogeneous architectures." — [Efficiency Mode (Windows), Grokipedia](https://grokipedia.com/page/Efficiency_mode_Windows)
- Manual activation path: Task Manager → Processes → right-click → Efficiency Mode. — [Efficiency Mode (Windows), Grokipedia](https://grokipedia.com/page/Efficiency_mode_Windows)
- Automatic appearance of the green leaf icon occurs when browsers (Edge, Chrome) independently apply internal EcoQoS optimizations without user action. — [Efficiency Mode (Windows), Grokipedia](https://grokipedia.com/page/Efficiency_mode_Windows)
- EcoQoS "always favors energy efficiency regardless of whether the system is on battery or plugged in" — unlike Power Throttling which is more aggressive on battery. — [Efficiency Mode (Windows), Grokipedia](https://grokipedia.com/page/Efficiency_mode_Windows)
- Efficiency Mode was introduced in Windows 11 22H2. — [Turn off efficiency mode, Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/3860984/turn-off-efficiency-mode-windows-11-forever)
- As of Windows 25H2, Power Throttling has become more aggressive even on desktop (plugged-in) systems. — [Windows 11 secretly throttling apps, Tweaktown](https://www.tweaktown.com/guides/11436/windows-11-is-secretly-throttling-your-apps-heres-how-to-catch-it/index.html)

### Inferences
- Efficiency Mode's green leaf is an indicator of EcoQoS, not a separate mechanism — anything that sets EcoQoS via `SetProcessInformation` will show the leaf in Task Manager.
- The combination of priority drop to Low (scheduling) + EcoQoS (power management) makes Efficiency Mode more aggressive than ProBalance's default Below Normal priority adjustment.

### Gaps
- No public documentation of the exact QoS API parameters Windows uses internally when the OS auto-classifies a background process (the heuristic path).


## Windows Built-in Automatic Process Throttling (Beyond EcoQoS)

### Takeaway
Windows has a layered automatic throttling system based on a formal QoS hierarchy (High/Medium/Low/Utility/Eco/Media/Deadline) that automatically classifies processes by window visibility, focus, audio state, and thread priority heuristics.

### Cited Findings
- The Windows QoS system (Power Throttling) has seven levels: High, Medium, Low, Utility, Eco, Media, Deadline. Classification sources include window visibility/focus, audio playback detection, explicit API tags, MMCSS media threads, and a heuristic fallback. — [Quality of Service, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- Automatic QoS classification by window state: In Focus → High QoS; Visible → Medium QoS; Minimized or fully occluded → Low QoS. — [Quality of Service, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- Processes playing audio are automatically assigned High QoS regardless of window state. — [Quality of Service, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- Heuristic fallback: "threads which are not classified by the above sources are automatically assigned a QoS level by the system. These heuristics include (but are not limited to) thread priority, where threads running with reduced thread priority can imply a lower QoS level." — [Quality of Service, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- Session-0 background services are assigned "Utility" QoS (introduced Windows 11 22H2). — [Quality of Service, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- A user-inactivity feature (introduced Ge 2025.05) lowers the foreground application's QoS from High to Medium after a period of no keyboard/mouse input, but only while on battery. Disabled via registry key `HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling\DisableUserPresenceQos = 1`. — [Quality of Service, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- Low and Utility QoS: "on battery, selects most efficient CPU frequency and schedules to efficient core." High QoS: "standard high performance." — [Quality of Service, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- Power Throttling was introduced in Windows 10 version 1709, initially requiring Intel Speed Shift (6th-gen+), but has been extended since. — [Introducing Power Throttling, Windows Insider Blog](https://blogs.windows.com/windows-insider/2017/04/18/introducing-power-throttling/)
- Power Throttling claimed "up to 11% CPU power savings for some of the most strenuous use cases." — [Introducing Power Throttling, Windows Insider Blog](https://blogs.windows.com/windows-insider/2017/04/18/introducing-power-throttling/)

### Inferences
- The window-visibility-based QoS mapping is the primary automatic throttling mechanism; it requires no explicit developer action and applies to all windowed processes.
- Thread priority as a heuristic signal means that if a developer already uses `SetThreadPriority(BELOW_NORMAL)` for background work, Windows may infer Utility/Low QoS automatically.

### Gaps
- The exact CPU frequency reduction percentage applied at each QoS level is not publicly documented (described as platform-dependent and tunable via Windows Provisioning).


## Windows Battery Saver / Energy Saver Mode Heuristics

### Takeaway
Legacy Battery Saver (pre-24H2) uses a simple battery percentage threshold (default 20%) to suspend background app execution. Windows 11 24H2 replaced it with "Energy Saver" which dynamically throttles background threads without a hard percentage threshold.

### Cited Findings
- Battery Saver activates automatically at 20% battery by default; user can configure any threshold 0–100% via PowerCfg. — [Enable or Disable Battery Saver, HTMD Blog](https://www.anoopcnair.com/enable-or-disable-battery-saver-in-windows-11/)
- "Battery Saver cuts off all background activity of all apps when battery drops below [the threshold], except for apps set to 'Always allowed.'" — [Battery Saver vs Energy Saver, WiseCleaner](https://www.wisecleaner.com/think-tank/898-Windows-11-Battery-Saver-vs-Energy-Saver-Whats-the-Difference.html)
- Windows 11 24H2 introduced "Energy Saver" to replace Battery Saver. Energy Saver "constantly and dynamically throttles background threads rather than using a simple percentage-based threshold." — [Energy Saver explained, Windows Forum](https://windowsforum.com/news/windows-11-energy-saver-and-adaptive-energy-saver-explained.389576/)
- An "Adaptive Energy Saver" variant also exists that adjusts throttle intensity based on current battery level, not just a binary on/off. — [Energy Saver explained, Windows Forum](https://windowsforum.com/news/windows-11-energy-saver-and-adaptive-energy-saver-explained.389576/)
- Battery Saver also dims the screen and disables sync/push notifications. — [Windows 11 Energy Saver guide, WinSides](https://winsides.com/energy-saver-option-windows-11-guide/)

### Inferences
- Energy Saver (24H2+) likely piggybacks on the same QoS infrastructure (Power Throttling) but applies throttling more aggressively or to more process categories than the normal background heuristics.

### Gaps
- The exact heuristics for which background threads Energy Saver throttles (vs. the always-allowed list) are not publicly documented.
- No documentation of how "Adaptive Energy Saver" scales intensity relative to battery level.


## Desktop Activity Moderator (DAM) — Screen Locked Process Handling

### Takeaway
The Desktop Activity Moderator is a kernel-mode driver for Connected Standby devices only (not triggered by screen lock on S3 systems). When connected standby is entered, session-0 services are throttled (cycled between suspended/running) and interactive session processes are fully suspended.

### Cited Findings
- DAM is present only on Windows 8+ client systems that support connected standby (AOAC field in SYSTEM_POWER_CAPABILITIES = TRUE). Not present on server SKUs or traditional S3 sleep machines. — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)
- Trigger condition: "connected standby" — device powered on, screen off. This is distinct from a simple screen lock on non-AOAC hardware. — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)
- Session 0 processes (services) → added to a throttling job object: "cycle between suspended and unsuspended (a large majority of time is spent in the suspended state)." — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)
- Interactive session processes (session 1+) → added to a suspension job object: "all threads suspended (not allowed to run under any circumstances); app state (process memory) is maintained." — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)
- DAM may unsuspend throttled services for longer periods if it detects "critical activities occurring." — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)
- Apps can opt in to receive `WM_POWERBROADCAST` (PBT_APMSUSPEND / PBT_APMRESUME) notification before DAM suspends them, via `RegisterSuspendResumeNotification` or `PowerRegisterSuspendResumeNotification`. — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)
- Windows Store apps are not impacted by DAM. — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)
- DAM uses nested job objects (supported since Windows 8) so it does not conflict with apps that already use job objects. — [Desktop Activity Moderator, Microsoft Learn](https://learn.microsoft.com/en-us/windows/compatibility/desktop-activity-moderator)

### Inferences
- DAM is not relevant for traditional desktop/tower PCs with S3 sleep — it only applies to tablet/laptop hardware certified for connected standby (InstantGo / Modern Standby).
- On Modern Standby hardware, DAM is effectively what enforces "app pause" behavior during screen-off, similar to mobile OS app suspension.

### Gaps
- What constitutes "critical activities" that cause DAM to unsuspend throttled services is not documented.
- How DAM interacts with the Modern Standby network proxying (allowing Windows Store apps to receive push notifications) is not detailed in this source.


## Process Explorer / Process Hacker Signals for Suspicious/Resource-Heavy Processes

### Takeaway
Process Explorer and System Informer (formerly Process Hacker) are primarily diagnostic and display tools, not automated flaggers; they surface raw metrics (CPU%, memory, handles, threads) rather than applying built-in heuristics to mark processes as suspicious or throttle-worthy.

### Cited Findings
- System Informer exposes per-process: loaded modules, active threads, open handles, and performance metrics. Users can manually suspend, kill, or restart processes. — [System Informer, Gizmodo](https://gizmodo.com/download/process-hacker)
- Common heuristics used by security tooling (EDR, SOC) include: process name matching a known system binary but running from unexpected directory (masquerading), abnormal CPU usage, execution from temp/staging directories, attempts to modify MBR/VBR, clearing of Windows event logs. — [Windows Suspicious Process, Rapid7 InsightIDR Docs](https://docs.rapid7.com/insightidr/windows-suspicious-process/)
- Process Hacker/System Informer does not have documented built-in auto-flagging heuristics for resource-heavy or suspicious processes in publicly available documentation. It is an inspection tool, not an automation engine.

### Inferences
- The resource-heaviness signals that matter in practice (sustained CPU%, working set size, I/O rate) are all visible in these tools, but acting on them requires user judgment or a separate automation layer (like Process Lasso's Watchdog or CPU Limiter).

### Gaps
- No primary source documentation of System Informer's internal highlighting/coloring rules for process anomalies was found. Would require examining source code at https://github.com/winsiderss/systeminformer.
- Process Explorer's "red/pink/green" color scheme for processes is documented informally in community posts but not in a formal Sysinternals whitepaper.


## Published Bitsum Whitepapers or Blog Posts on Algorithm Design

### Takeaway
Bitsum has published several blog posts explaining the rationale behind ProBalance and BHP but treats specific threshold values and internal algorithm logic as proprietary; no formal whitepaper with algorithmic pseudocode has been found.

### Cited Findings
- Bitsum's "How ProBalance Works" page (https://bitsum.com/how-probalance-works/) is the closest to a design document, but describes the algorithm at a high level using marketing language ("market intelligence, logic, user help") rather than technical specification. — [ProBalance How It Works, Bitsum](https://bitsum.com/how-probalance-works/)
- Bitsum published a post validating BHP's design approach when Intel released Speed Shift, framing the CPU unparking concept in hardware terms. — [Intel Speed Shift article, Bitsum](https://bitsum.com/product-update/intels-speed-shift-validates-parkcontrol-and-process-lasso/)
- The Process Lasso FAQ and documentation acknowledge configurable advanced parameters but do not publish default values. — [Process Lasso FAQ, Bitsum](https://bitsum.com/process-lasso-faq/)

### Inferences
- Exact thresholds are likely retained as a trade secret to differentiate Process Lasso from free alternatives. Users who need exact values would need to either inspect the settings UI or run empirical tests.

### Gaps
- No independent reverse-engineering or academic analysis of ProBalance's algorithm was found in the sources searched.
- Bitsum's GitHub repository (if any) was not searched — worth checking for any open-source components.
