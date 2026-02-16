from __future__ import annotations

import os
import resource


def _rss_from_proc() -> float | None:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        kb = float(parts[1])
                        return kb / 1024.0
    except Exception:
        return None
    return None


def _rss_from_rusage() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.name == "posix" and os.uname().sysname.lower() == "darwin":
        return rss / (1024 * 1024)
    return rss / 1024.0


def log_mem(tag: str) -> None:
    try:
        rss_mb = _rss_from_proc()
        if rss_mb is None:
            rss_mb = _rss_from_rusage()
        print(f"[mem] {tag} rss_mb={rss_mb:.1f}")
    except Exception:
        pass
