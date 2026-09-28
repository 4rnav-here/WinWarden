"""
get_signer(exe_path) — who signed an executable, via PowerShell. Cached per (path, mtime).
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from optimizer.platform import IS_WINDOWS

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Cache keyed by (normalized_path, mtime) so rebuilt binaries invalidate automatically.
_cache: dict[tuple[str, float], str | None] = {}


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _extract_o(subject: str) -> str | None:
    """Pull O= from a certificate DN, e.g. 'CN=Foo, O=Google LLC, C=US' → 'Google LLC'."""
    m = re.search(r"\bO=([^,]+)", subject)
    return m.group(1).strip() if m else None


def get_signer(exe_path: str) -> str | None:
    """
    Return the signing organisation (e.g. "Google LLC"), "NOT VALID (<status>)",
    or None if unsigned, non-Windows, or the path is inaccessible.
    Cached per (path, mtime) — repeated calls for the same binary are free.
    """
    if not IS_WINDOWS or not exe_path:
        return None

    key = (exe_path, _mtime(exe_path))
    if key in _cache:
        return _cache[key]

    escaped = exe_path.replace("'", "''")
    ps_cmd = (
        f"Get-AuthenticodeSignature -LiteralPath '{escaped}' | ConvertTo-Json -Depth 3"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        _cache[key] = None
        return None

    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        _cache[key] = None
        return None

    status = data.get("Status", -1)
    if status == 0:  # Valid
        cert = data.get("SignerCertificate")
        if isinstance(cert, dict):
            signer = _extract_o(cert.get("Subject", ""))
            _cache[key] = signer
            return signer
        _cache[key] = None
        return None

    msg = data.get("StatusMessage") or f"status {status}"
    result = f"NOT VALID ({msg})"
    _cache[key] = result
    return result
