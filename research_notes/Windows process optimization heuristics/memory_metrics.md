# Windows Memory Metrics

## What is "working set" and why can it be misleading?

### Takeaway
Working set is the subset of a process's virtual address space currently resident in physical RAM; it includes both private and shared pages, making it an unreliable signal for "how much RAM does this process cost the system" because shared pages get double-counted across processes.

### Cited Findings
- The working set is "the physical memory that Windows gives to your process, given to you when you demand it by touching the virtual address space." A process starts with an empty working set and incurs page faults as it references pages. — [PDC10: Mysteries of Windows Memory Management Revealed: Part Two (Microsoft Learn)](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- The working set consists of both shareable and private pages; shareable working set is effectively counted as "private" only if it is not actually shared with another process. — [PDC10: Mysteries of Windows Memory Management Revealed: Part Two](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- The working set does not include trimmed memory that is still cached (pages on the standby list are not in the working set but still in RAM). — [PDC10: Mysteries of Windows Memory Management Revealed: Part Two](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- "Summing Working Sets across processes may double-count shared pages." Multiple processes can share DLL code and memory-mapped file pages, so the aggregate working set overstates system-wide RAM use. — [Windows Memory Usage: Working Set vs. Commit (KomuraSoft LLC Blog)](https://comcomponent.com/en/blog/windows-memory-usage-working-set-commit/)
- Working Set is larger than private bytes because it includes shared resources that multiple processes can access, and unlike private bytes, it can include non-paged private bytes as well as memory-mapped files. — [Private Bytes, Virtual Bytes, Working Set (Tutorialspoint)](https://www.tutorialspoint.com/private-bytes-virtual-bytes-working-set)
- Working set reflects how much virtual memory currently resides in physical RAM at a moment in time; the kernel decides which pages stay resident versus being pushed to the paging file. — [Process Explorer: Private Bytes vs Working Set Explained](https://sse.to/blog/process-explorer-private-bytes-vs-working-set/)
- "Working Set is the wrong metric for capacity planning on Windows servers." — [Process Explorer: Private Bytes vs Working Set Explained](https://sse.to/blog/process-explorer-private-bytes-vs-working-set/)

### Inferences
- Because working set includes shared DLL pages counted once per process, comparing two processes by working set will systematically overstate the memory cost of processes that load many shared libraries.
- Working set fluctuates as the OS trims and re-faults pages; a process under memory pressure will show a lower working set even though it hasn't freed memory—it's just been pushed out.

### Gaps
- No primary source was found quantifying the average magnitude of shared-page overcount on a typical Windows 10/11 desktop system.

---

## What is "private bytes" / "private working set" / PrivateUsage?

### Takeaway
Private bytes (also called Commit Size in Task Manager and PrivateUsage in WMI) is the committed virtual memory exclusive to a process that cannot be shared; it represents the OS's promise to back that memory with RAM or page file. Private *working set* is the subset of private bytes currently in RAM.

### Cited Findings
- "Private Bytes answers the question: how much memory has a process committed for its own use that cannot be shared with any other process?" Includes stacks, heaps, raw virtual allocations, page tables, and read/write portions of image and file mappings. — [Private Bytes, Virtual Bytes, Working Set (Tutorialspoint)](https://www.tutorialspoint.com/private-bytes-virtual-bytes-working-set)
- "The Private Bytes counter reports the commit charge of the process. That is to say, the amount of space that has been allocated in the swap file to hold the contents of the private memory in the event that it is swapped out." — [Private Bytes Performance Counter — Beware! (Microsoft Learn / Rico Mariani)](https://learn.microsoft.com/en-us/archive/blogs/ricom/private-bytes-performance-counter-beware)
- Private bytes always indicate the memory *allocated*, not the memory actively *used* by the process — a process can commit memory that is never made resident. — [Private Bytes, Virtual Bytes, Working Set (Tutorialspoint)](https://www.tutorialspoint.com/private-bytes-virtual-bytes-working-set)
- **Critical caveat**: "The Private Bytes counter is definitely overstating the true cost." Windows must pre-allocate page-file space at commit time even for static data that may never be read or written. Rico Mariani (Microsoft) reported a managed app showing ~7888 KB private bytes while the actual memory pressure was far less. — [Private Bytes Performance Counter — Beware! (Microsoft Learn)](https://learn.microsoft.com/en-us/archive/blogs/ricom/private-bytes-performance-counter-beware)
- "Commit Size in Task Manager is called Private Bytes in Process Explorer and Performance Monitor." These are the same metric presented under different names. — [Memory Information in Task Manager (Pavel Yosifovich / scorpiosoftware.net)](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)
- Task Manager's Details tab column "Memory (Active Private Working Set)" shows only RAM-resident private pages; UWP apps show zero when minimized because threads are suspended. — [Memory Information in Task Manager](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)
- Private working set = private committed pages currently in RAM (subset of private bytes). It excludes shared pages and excludes private pages currently on the standby/modified list. — [Memory Information in Task Manager](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)

### Inferences
- Private bytes is the right metric for detecting memory *leaks* (allocations that grow without bound) because it tracks committed virtual memory regardless of paging state.
- For "how much RAM does this process occupy right now," private working set is more precise than full private bytes but can understate if the process has recently been trimmed.

### Gaps
- No source was found that clearly documents how PrivateUsage in WMI (as returned by Win32_Process) differs from Process.PrivateMemorySize64 in .NET; they appear equivalent but this was not confirmed by a primary source.

---

## What is "commit charge" / "virtual memory"?

### Takeaway
Commit charge is the OS's system-wide promise to back virtual memory: the sum of all committed private virtual memory across all processes, bounded by RAM + page file. It measures fiscal risk to the system, not current RAM use.

### Cited Findings
- "Commit charge is the total amount of virtual memory of all processes that must be backed by either physical memory or the page file." It cannot exceed RAM + page file size combined. — [Commit Charge (Wikipedia)](https://en.wikipedia.org/wiki/Commit_charge)
- When Windows reports "low virtual memory" and suggests increasing the paging file, it means System Commit Charge has approached the System Commit Limit (RAM + page file). — [Commit Charge (Wikipedia)](https://en.wikipedia.org/wiki/Commit_charge)
- The system dynamically expands page files when total commit charge approaches the limit, but this causes performance degradation. — [Commit Charge (Wikipedia)](https://en.wikipedia.org/wiki/Commit_charge)
- There is "almost no connection between virtual and physical memory. The only connection is that the system commit limit is the sum of physical memory and the size of the paging file(s)." — [PDC10: Mysteries of Windows Memory Management Revealed (Microsoft Learn)](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- Per-process, Task Manager shows "Commit Size" (Vista+) or "VM size" (XP/Server 2003); the system-level total commit cannot be derived from summing per-process values because system allocations (paged pool, kernel) are excluded. — [Commit Charge (Wikipedia)](https://en.wikipedia.org/wiki/Commit_charge)
- A virtual address reservation (MEM_RESERVE) claims address space without backing resources and does NOT count against commit. Only committed pages (MEM_COMMIT) count. — [Windows Memory Usage: Working Set vs. Commit](https://comcomponent.com/en/blog/windows-memory-usage-working-set-commit/)
- "True pressure" signal: system commit charge approaching commit limit — not low free RAM. — [Windows Memory Usage: Working Set vs. Commit](https://comcomponent.com/en/blog/windows-memory-usage-working-set-commit/)

### Inferences
- A process can have a large commit size (private bytes) and still use very little RAM if those committed pages have never been touched; the risk to the system is that if all those pages were demanded simultaneously, the system could run out of commit capacity.
- Commit size is a better "worst-case RAM demand" metric than working set, but private bytes' overstatement caveat still applies.

### Gaps
- The precise relationship between per-process commit size and system commit charge under memory compression (a Windows 10/11 feature) was not found in a primary source.

---

## What is "shared memory" and why does counting it per-process double-count?

### Takeaway
Shared memory includes pages from shared DLLs, memory-mapped files, and copy-on-write mappings that can be simultaneously mapped into multiple process address spaces; summing working sets across processes counts these pages once per process, inflating the apparent total RAM demand.

### Cited Findings
- "Multiple processes can share DLL code and memory-mapped file pages. Summing Working Sets across processes may double-count shared pages." — [Windows Memory Usage: Working Set vs. Commit](https://comcomponent.com/en/blog/windows-memory-usage-working-set-commit/)
- Task Manager's Details tab exposes a "Memory (Shared Working Set)" column that shows the shared portion separately. Process Explorer splits Working Set into WS Private and WS Shareable. — [Memory Information in Task Manager](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)
- "Most of the memory would be shared so the second managed application would have much less impact on your system." Example: a .NET app where DLL private bytes dropped from 37% to less than 7% of total between .NET 1.1 and 2.0—the incremental cost of a second instance was correspondingly lower. — [Private Bytes Performance Counter — Beware! (Microsoft Learn)](https://learn.microsoft.com/en-us/archive/blogs/ricom/private-bytes-performance-counter-beware)
- Shareable working set is effectively counted as "private" only if it is not actually shared with another process. — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)

### Inferences
- The only way to avoid double-counting is to use private bytes / commit size as the ranking metric (it excludes shared pages by definition) and separately track system-wide shared page consumption via RAMMap or perfmon.

### Gaps
- No authoritative source was found on how copy-on-write (COW) pages transition from shared to private and whether Task Manager's columns update in real time for that transition.

---

## What does it mean when a process has a large working set but low private bytes?

### Takeaway
Large working set + low private bytes means the process's RAM footprint is dominated by shared pages (DLLs, memory-mapped files, copy-on-write mappings) that it uses but does not own; the process contributes little exclusive memory pressure to the system.

### Cited Findings
- "A process can exhibit a large working set with low private bytes when the memory manager has trimmed cold pages to the paging file. These pages will soft-fault back into memory if accessed again — this scenario isn't inherently problematic." — [Process Explorer: Private Bytes vs Working Set Explained](https://sse.to/blog/process-explorer-private-bytes-vs-working-set/)
- The opposite pattern — "steadily climbing private bytes paired with a stable working set — indicates the classic leaked-but-untouched allocation pattern." The application allocates without freeing, yet doesn't read the leaked regions, so RAM usage appears normal until the commit limit is exceeded. — [Process Explorer: Private Bytes vs Working Set Explained](https://sse.to/blog/process-explorer-private-bytes-vs-working-set/)
- Working set includes both private and shared components; private bytes does not include shared pages. So working set > private bytes whenever the process uses shared DLL or mapped-file pages. — [Private Bytes, Virtual Bytes, Working Set (Tutorialspoint)](https://www.tutorialspoint.com/private-bytes-virtual-bytes-working-set)

### Inferences
- A process like a web browser that loads many large shared DLLs and memory-maps files will show a high working set but relatively low private bytes. Targeting such a process in an optimizer based on working set alone is misleading — its "apparent" RAM cost is inflated by shared pages that would remain in RAM even if it were killed (they'd still be needed by other processes).

### Gaps
- No source confirmed the exact mechanics of how memory-mapped file pages appear in working set vs. private bytes across different mapping types (read-only vs. copy-on-write).

---

## What is "memory pressure" from the OS's perspective — how does Windows decide it needs to start paging?

### Takeaway
Windows uses a demand-paging model with local page replacement; memory pressure is triggered not by low free RAM but by depletion of the free and zeroed page lists, at which point the memory manager begins trimming working sets using a least-recently-used (LRU) policy.

### Cited Findings
- Windows uses a "local page replacement policy, meaning that it will pull the pages from the requesting process" when that process's working set exceeds acceptable limits. — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- "At some point, the memory manager decides the process is large enough; it then gives up pages to make room for new pages... it will start to pull pages out of the working set that are least recently used before it will allocate new memory to that process." — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- Page allocation priority: memory manager first uses zero/free pages, then standby pages, then forces the modified page writer to flush modified pages to disk (converting them to standby), and only then trims working sets. Trimmed pages go to the modified or standby list depending on whether they contain dirty private data. — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- "If memory demand runs high or the modified list has grown beyond a certain threshold, the memory manager arranges to write pages from modified memory to the page file on hard disk, and moves those pages from Modified to Free memory." — from Windows memory management search results
- "True pressure" signal: System Commit approaching Commit Limit (not low free RAM). "Low free RAM" is a misleading signal because it doesn't account for the reusable standby cache. — [Windows Memory Usage: Working Set vs. Commit](https://comcomponent.com/en/blog/windows-memory-usage-working-set-commit/)
- The "\Memory\Modified Page List Bytes" performance counter measures the size of the modified page list — data waiting to be written to disk. When this grows, the modified page writer must flush before new pages can be allocated. — from search results citing Windows Performance documentation

### Inferences
- An optimizer that simply tries to reduce working sets by terminating processes may actually worsen system performance by causing hard page faults when those pages are needed again and must be re-read from disk.
- The real signal of impending performance degradation is elevated hard page faults combined with commit approaching the commit limit, not a large standby or cached value.

### Gaps
- The specific thresholds at which Windows begins working set trimming (the "memory manager decides the process is large enough" logic) are not documented in public sources found; they appear to be an internal kernel heuristic.

---

## What is the "modified page list" and how does it factor into memory pressure?

### Takeaway
The modified page list holds pages that have been dirtied (written to) since they were last backed to disk; they must be flushed by the modified page writer before they can become standby pages or be reallocated, making a large modified list a bottleneck that delays RAM recovery under pressure.

### Cited Findings
- "Modified pages have been changed in some way since they were last written to disk, and therefore must have their contents saved by the modified page writer before becoming standby pages." — from Windows memory management documentation (search result citing Windows Kernel Internals)
- "If memory demand runs high or the modified list has grown beyond a certain threshold, the memory manager arranges to write pages from the modified memory to the page file on hard disc, and moves those pages from the Modified to the Free memory." — from search results citing Windows Performance documentation
- The memory manager's page list priority order: free → zero → standby → modified (once written) → trim working sets. The modified list is a bottleneck in this chain because its pages require disk I/O before reuse. — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- "There are two threads specifically responsible for moving pages between lists. Firstly, the zero page thread... Secondly, the modified page writer is responsible for moving pages from the modified page list to the standby page list, first writing out any data." — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- The "\Memory\Modified Page List Bytes" performance counter measures the total modified data waiting to be written to disk. — from Windows Performance documentation search results

### Inferences
- A system with a large modified page list and heavy disk I/O on the page file is under real memory pressure, not just "low free RAM." This is a meaningful diagnostic signal.
- Processes that perform frequent private writes (databases, compilers, video editors) will feed the modified list heavily; these are processes whose memory activity has real system cost beyond just their RAM footprint.

### Gaps
- No source found on the exact threshold that triggers the modified page writer to begin flushing proactively vs. reactively (only that "a certain threshold" exists).

---

## What does Task Manager's "Memory" column actually show vs. what Process Explorer shows?

### Takeaway
Task Manager's default "Memory" column shows "Active Private Working Set" — RAM-resident private pages, excluding shared memory and excluding paged-out private pages; Process Explorer exposes Private Bytes, WS Private, WS Shareable, and Virtual Size simultaneously, giving a far more complete picture.

### Cited Findings
- Task Manager's Processes tab "Memory" column = **Active Private Working Set**: RAM currently used by the process that isn't shared with others. For UWP apps, shows zero when minimized (threads suspended). — [Memory Information in Task Manager (Pavel Yosifovich)](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)
- Task Manager Details tab optional columns include: Memory (Active Private Working Set), Memory (Private Working Set), Commit Size, Working Set, Peak Working Set, Memory (Shared Working Set), Working Set Delta. — [Memory Information in Task Manager](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)
- **Commit Size** in Task Manager Details tab = **Private Bytes** in Process Explorer = **PrivateMemorySize64** in .NET = **PrivateUsage** in WMI: the total committed private memory. The author of the scorpiosoftware post calls this "the most accurate indicator of actual memory consumption." — [Memory Information in Task Manager](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)
- "Task Manager's 'Commit Size' corresponds to 'Private Bytes' in Process Explorer and Performance Monitor." — [Process Explorer: Private Bytes vs Working Set Explained](https://sse.to/blog/process-explorer-private-bytes-vs-working-set/)
- "Task Manager only offers the private working set figure; Process Explorer gives you a more detailed view." — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- Process Explorer splits Working Set into WS Private and WS Shareable, and separately shows Private Bytes (commit) and Virtual Size. — [Be careful using Task Manager for Memory Metrics (MahdyTech)](https://mahdytech.com/2019/01/05/task-manager-memory-info/)
- Task Manager obscures paged memory information and omits virtual (reserved) space metrics entirely; discrepancies become significant for data-intensive services on high-memory systems. — [Be careful using Task Manager for Memory Metrics](https://mahdytech.com/2019/01/05/task-manager-memory-info/)

### Inferences
- The default Task Manager "Memory" column is the least representative metric for an optimizer — it hides paged-out private memory, hides shared pages (which at least prevents double-counting), and zeros out for minimized UWP apps.
- Adding "Commit Size" to Task Manager Details tab brings it up to the same level as Process Explorer's Private Bytes, making it actionable without a third-party tool.

### Gaps
- No source found confirming how Task Manager's "Memory" column handles Windows 11's memory compression (Compressed memory) — whether compressed private pages count toward Active Private Working Set or appear as zero until accessed.

---

## Which metric should an optimizer use to rank processes by "memory impact"?

### Takeaway
For ranking processes by exclusive memory pressure on the system, **Private Bytes / Commit Size** is the correct primary metric; for ranking by current RAM occupancy, **Private Working Set** (not full working set) avoids shared-page double-counting while reflecting what's actually in RAM.

### Cited Findings
- "Commit Size is the correct column to look at when trying to ascertain memory consumption in processes." — [Memory Information in Task Manager (Pavel Yosifovich)](https://scorpiosoftware.net/2023/04/12/memory-information-in-task-manager/)
- "If you want to know which processes are occupying RAM right now, look at working set and private working set. If you are investigating a leak in application allocations, private bytes or commit size usually matter more." — from search results citing Windows optimization community
- "Private Bytes plus a buffer for shared working set better reflects actual memory needs" than working set alone. — [Process Explorer: Private Bytes vs Working Set Explained](https://sse.to/blog/process-explorer-private-bytes-vs-working-set/)
- Private bytes can overstate true cost because committed memory that is never made resident still counts. Rico Mariani's example: a managed app showed ~7888 KB private bytes but the actual working memory pressure was far less. — [Private Bytes Performance Counter — Beware! (Microsoft Learn)](https://learn.microsoft.com/en-us/archive/blogs/ricom/private-bytes-performance-counter-beware)
- "Which metric to look at depends on what you want to know": RAM right now = working set / private working set; leak detection = private bytes; system commit capacity = commit size; full virtual footprint = virtual size. — from search results synthesizing Windows optimization community consensus

### Inferences
- An optimizer targeting "which process to suspend or throttle to free RAM now" should rank by Private Working Set (WS Private in Process Explorer), as it represents exclusive RAM with no shared-page inflation.
- An optimizer targeting "which process is most at risk of causing commit exhaustion or swap pressure" should rank by Private Bytes / Commit Size.
- Combining both (e.g., rank by Private Working Set, secondary sort by Commit Size) covers both dimensions.
- Working set (total, including shared) should not be used as the primary ranking metric; it will systematically over-rank processes that use many shared libraries.

### Gaps
- No primary source was found with a recommendation specific to Windows 10/11 memory compression: it is unclear how compressed private pages should factor into optimizer metrics.

---

## What is "standby memory" and why do RAM cleaners that empty it make performance worse?

### Takeaway
Standby memory is RAM holding pages that have been removed from process working sets but whose content is still valid on disk; it acts as a disk cache that satisfies page faults without disk I/O (soft faults). "Cleaning" it forces the next access to re-read from disk (a hard fault), making performance worse.

### Cited Findings
- Standby pages are "still associated with a process but not included in the working set"; their content has not changed since last written to disk, so they can be reused without a disk write. — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- Task Manager's "Available" field = free + zeroed + standby pages. "Cached" field = standby + modified + system working set. Low "Free" is therefore normal and does not indicate memory pressure. — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- "Having a low 'free memory' value in Windows is normal — and a good thing. In fact, a technology like SuperFetch has the goal of reducing free memory (moving pages from the free to the standby list as it caches files into memory)." — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- There are eight standby page lists in Windows Vista and above (prioritized by importance), so the memory manager scavenges the least-important standby pages first. — [PDC10: Mysteries of Windows Memory Management Revealed](https://learn.microsoft.com/en-us/archive/blogs/tims/pdc10-mysteries-of-windows-memory-management-revealed-part-two)
- A soft page fault occurs when a trimmed page on the standby list is re-referenced: "the page is moved from the standby list and back into the working set of the process without the process knowing about this exchange" — no disk I/O required. — from search results citing smallvoid.com / Windows page fault documentation
- "A RAM cleaner can make the number look better, but it can also force Windows to reload data later — sometimes causing more disk activity, more stutter, and slower app switching." — [How to Clear RAM Cache in Windows 11 (Windows Forum)](https://windowsforum.com/news/how-to-clear-ram-cache-in-windows-11-standby-memory-rammap-restart.407675/)
- "Clearing standby list is not worth it and will decrease performance." — [is it worth it clearing standby list? (Eleven Forum)](https://www.elevenforum.com/t/is-it-worth-it-clearing-standby-list.38462/)
- "Many 'RAM cleaner' apps simply force the system to dump useful cache and make the free-RAM number look prettier than it should, which is cosmetic improvement, not performance engineering." — [RAM Cleaner for Windows 10/11 (en.ittrip.xyz)](https://en.ittrip.xyz/windows/ram-cleaner-mem-reduct)
- Windows automatically reclaims standby pages when active processes need RAM; "the operating system will likely just fill the standby memory again after it's cleared." — [Releasing Standby memory (TenForums)](https://www.tenforums.com/performance-maintenance/148760-releasing-standby-memory.html)

### Inferences
- An optimizer should never empty the standby list as an "optimization" action. The correct optimizer behavior is to avoid touching standby memory entirely and focus on reducing private bytes / commit size of living processes.
- The only scenario where clearing standby list is defensible is if a specific page list has grown anomalously large due to a faulty driver or kernel leak (diagnosable via RAMMap), not as a routine "clean RAM" operation.

### Gaps
- No primary source was found on whether Windows 11's memory compression interacts with the standby list (whether compressed pages appear on the standby list, or a separate compressed store list).
