from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import streamlit as st


@dataclass(frozen=True)
class SessionSnapshot:
    ts_utc: str
    date: str
    session_id: str
    visitor_id: str
    pages_visited: str
    event_count: int
    error_count: int
    total_runtime_ms: int
    app_version: str
    last_page: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _state() -> dict:
    return st.session_state


def ensure_session_id() -> str:
    state = _state()
    if "telemetry_session_id" not in state:
        state["telemetry_session_id"] = os.urandom(12).hex()
    return state["telemetry_session_id"]


def _browser_fingerprint_seed() -> str:
    try:
        context = getattr(st, "context", None)
        if context is None:
            return ""
        headers = getattr(context, "headers", None)
        if headers is None:
            return ""
        if hasattr(headers, "items"):
            header_items = headers.items()
        else:
            header_items = dict(headers).items()
        normalized = {str(key).lower(): str(value) for key, value in header_items}
        pieces = [
            normalized.get("cf-connecting-ip", ""),
            normalized.get("x-forwarded-for", ""),
            normalized.get("user-agent", ""),
            normalized.get("accept-language", ""),
        ]
        return "|".join(piece.strip() for piece in pieces if piece and piece.strip())
    except Exception:
        return ""


def ensure_visitor_id() -> str:
    state = _state()
    if "telemetry_visitor_id" in state:
        return state["telemetry_visitor_id"]

    seed = _browser_fingerprint_seed()
    if seed:
        salt = os.environ.get("TELEMETRY_VISITOR_SALT", "")
        digest = hashlib.sha256(f"{salt}|{seed}".encode("utf-8")).hexdigest()[:20]
        visitor_id = f"v_{digest}"
    else:
        visitor_id = f"v_{os.urandom(10).hex()}"
    state["telemetry_visitor_id"] = visitor_id
    return visitor_id


def ensure_session_started() -> None:
    state = _state()
    if "telemetry_started" in state:
        return
    state["telemetry_started"] = True
    state["telemetry_session_start_logged"] = False
    state["telemetry_started_ts"] = time.time()
    state["telemetry_pages"] = set()
    state["telemetry_event_count"] = 0
    state["telemetry_error_count"] = 0


def register_page(page: str) -> None:
    state = _state()
    pages = state.get("telemetry_pages")
    if pages is None:
        pages = set()
    pages.add(page)
    state["telemetry_pages"] = pages
    state["telemetry_last_page"] = page


def increment_event() -> None:
    state = _state()
    state["telemetry_event_count"] = int(state.get("telemetry_event_count", 0)) + 1


def increment_error() -> None:
    state = _state()
    state["telemetry_error_count"] = int(state.get("telemetry_error_count", 0)) + 1


def snapshot(app_version: str) -> SessionSnapshot:
    state = _state()
    session_id = ensure_session_id()
    visitor_id = ensure_visitor_id()
    pages = sorted(state.get("telemetry_pages", set()))
    now = time.time()
    started = state.get("telemetry_started_ts", now)
    total_runtime_ms = int((now - started) * 1000)
    return SessionSnapshot(
        ts_utc=_utc_now_iso(),
        date=_today_date(),
        session_id=session_id,
        visitor_id=visitor_id,
        pages_visited=",".join(pages),
        event_count=int(state.get("telemetry_event_count", 0)),
        error_count=int(state.get("telemetry_error_count", 0)),
        total_runtime_ms=total_runtime_ms,
        app_version=app_version,
        last_page=state.get("telemetry_last_page", ""),
    )
