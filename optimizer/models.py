from typing import Literal

from pydantic import BaseModel


class ProcessRef(BaseModel):
    """Identity token passed to every action tool. Combines pid + create_time so reused PIDs are caught."""
    pid: int
    create_time: float
    name: str
    exe: str = ""


class ToolResult(BaseModel):
    """Returned by every action tool."""
    ok: bool
    reason: str = ""
    undo: dict = {}


class SystemPressure(BaseModel):
    cpu_percent: float
    ram_percent: float
    commit_ratio: float | None        # CommitTotal / CommitLimit; Windows only
    hard_faults_per_s: float | None   # pages read from disk per second; Windows only
    disk_busy_percent: float | None


class ProcessInfo(BaseModel):
    pid: int
    create_time: float
    name: str
    exe: str
    username: str
    ppid: int
    cpu_percent: float          # % of one core since last sample
    private_mb: float           # commit size — virtual memory reserved exclusively for this process
    wset_mb: float = 0.0        # working set — physical RAM currently occupied (includes shared pages)
    io_bytes_total: int
    num_threads: int
    priority: int | None
    # Populated only by get_process_details(), empty/None for list_processes()
    parent_name: str = ""
    uptime_s: float | None = None


class KnownProcess(BaseModel):
    name: str
    category: Literal[
        "core_system", "security", "driver_helper",
        "user_app", "useful_background", "bloat",
    ]
    description: str
    path_hint: str = ""
