from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any

from shared.logging.ops import set_log_context
from shared.telemetry import log_event
from shared.telemetry.session import ensure_session_id


_LOGGER = logging.getLogger("app.errors")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_app_version() -> str:
    return os.environ.get("APP_VERSION", "dev")


def _get_git_sha(app_version: str) -> str:
    return os.environ.get("GIT_SHA", "") or app_version


def _get_instance_id() -> str:
    return os.environ.get("FLY_ALLOC_ID") or os.environ.get("HOSTNAME") or "local"


def log_exception(exc: Exception, trace_id: str, page_id: str, extra: dict | None) -> None:
    extra = extra or {}
    session_id = ""
    try:
        session_id = ensure_session_id()
    except Exception:
        session_id = ""

    try:
        set_log_context(page=page_id, session_id=session_id or None)
    except Exception:
        pass

    app_version = _get_app_version()
    git_sha = _get_git_sha(app_version)
    instance_id = _get_instance_id()
    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    payload: dict[str, Any] = {
        "trace_id": trace_id,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "traceback": stack,
        "page_id": page_id,
        "session_id": session_id,
        "app_version": app_version,
        "git_sha": git_sha,
        "instance_id": instance_id,
        "ts_utc": _utc_now_iso(),
        "context": extra,
    }

    try:
        _LOGGER.error(
            "Unhandled exception [%s] page=%s session=%s",
            trace_id,
            page_id,
            session_id or "",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"page": page_id, "session_id": session_id, "trace_id": trace_id},
        )
    except Exception:
        pass

    try:
        log_event("error", page_id, payload=payload)
    except Exception as err:
        try:
            _LOGGER.error("Telemetry log_event failed for %s: %s", trace_id, err)
        except Exception:
            pass
