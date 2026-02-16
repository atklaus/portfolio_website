from __future__ import annotations

import sys
import time
import traceback
from contextlib import contextmanager
from typing import Any

import streamlit as st

from .config import TelemetryConfig, get_config
from shared.logging.ops import set_log_context
from .session import (
    ensure_session_id,
    ensure_session_started,
    increment_error,
    increment_event,
    register_page,
    snapshot,
)
from .sinks import build_sinks


def _state() -> dict:
    return st.session_state


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _get_sinks(config: TelemetryConfig):
    state = _state()
    sinks = state.get("telemetry_sinks")
    if sinks is None:
        sinks = build_sinks(config)
        state["telemetry_sinks"] = sinks
    return sinks


def _buffer_event(config: TelemetryConfig, event: dict) -> None:
    state = _state()
    buffer = state.get("telemetry_buffer")
    if buffer is None:
        buffer = []
        state["telemetry_buffer"] = buffer
    buffer.append(event)
    if len(buffer) > config.max_buffer:
        buffer.pop(0)
    increment_event()
    if event.get("event_type") == "error":
        increment_error()
    if event.get("event_type") == "page_view":
        register_page(event.get("page", ""))
    state["telemetry_last_page"] = event.get("page", "")


def _flush_events(config: TelemetryConfig) -> None:
    state = _state()
    buffer = state.get("telemetry_buffer", [])
    if not buffer:
        return
    session_id = ensure_session_id()
    sinks = _get_sinks(config)
    success = True
    for sink in sinks:
        if not sink.write_events(buffer, session_id):
            success = False
    if success:
        state["telemetry_buffer"] = []
        state["telemetry_last_flush"] = time.time()


def _flush_session_snapshot(config: TelemetryConfig) -> None:
    snap = snapshot(config.app_version)
    sinks = _get_sinks(config)
    for sink in sinks:
        try:
            sink.write_session(snap)
        except Exception:
            pass
    _state()["telemetry_last_session_flush"] = time.time()


def log_event(
    event_type: str,
    page: str,
    payload: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    config = get_config()
    if not config.enabled:
        return
    try:
        ensure_session_started()
        session_id = ensure_session_id()
        set_log_context(page=page, session_id=session_id)
        event = {
            "ts_utc": _utc_now_iso(),
            "session_id": session_id,
            "page": page,
            "event_type": event_type,
            "duration_ms": duration_ms,
            "payload": payload or {},
            "app_version": config.app_version,
        }
        _buffer_event(config, event)
        now = time.time()
        last_flush = _state().get("telemetry_last_flush", 0)
        if len(_state().get("telemetry_buffer", [])) >= config.flush_events or (
            now - last_flush
        ) >= config.flush_seconds:
            _flush_events(config)
        last_session_flush = _state().get("telemetry_last_session_flush", 0)
        if event_type in ("session_start", "session_flush") or (
            now - last_session_flush
        ) >= config.session_flush_seconds:
            _flush_session_snapshot(config)
    except Exception as exc:
        print(f"Telemetry log_event failed: {exc}")


def log_page_view(page: str) -> None:
    log_event("page_view", page, payload={})


def log_error(page: str, exc: BaseException) -> None:
    try:
        stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log_event(
            "error",
            page,
            payload={
                "error": str(exc),
                "traceback": stack,
            },
        )
    except Exception as err:
        print(f"Telemetry log_error failed: {err}")


@contextmanager
def track_timing(page: str, payload: dict | None = None):
    start = time.time()
    try:
        yield
        duration_ms = int((time.time() - start) * 1000)
        log_event("pipeline_run", page, payload={**(payload or {}), "status": "success"}, duration_ms=duration_ms)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        log_event(
            "pipeline_run",
            page,
            payload={**(payload or {}), "status": "error", "error": str(exc)},
            duration_ms=duration_ms,
        )
        raise


def _install_excepthook(page: str) -> None:
    state = _state()
    if state.get("telemetry_excepthook_installed"):
        return

    def _hook(exc_type, exc, tb):
        try:
            stack = "".join(traceback.format_exception(exc_type, exc, tb))
            log_event(
                "error",
                page,
                payload={
                    "error": str(exc),
                    "traceback": stack,
                },
            )
        except Exception:
            pass
        return sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
    state["telemetry_excepthook_installed"] = True


def instrument_page(page: str) -> None:
    config = get_config()
    if not config.enabled:
        return
    ensure_session_started()
    set_log_context(page=page, session_id=ensure_session_id())
    state = _state()
    if not state.get("telemetry_session_start_logged"):
        log_event("session_start", page, payload={})
        state["telemetry_session_start_logged"] = True
    log_page_view(page)
    _install_excepthook(page)


def instrument_page_safe(page: str, fn):
    try:
        instrument_page(page)
        return fn()
    except Exception as exc:
        log_error(page, exc)
        raise


@contextmanager
def page_guard(page: str):
    """Guard a page body to ensure exceptions are logged even if Streamlit catches them."""
    try:
        instrument_page(page)
        yield
    except Exception as exc:
        log_error(page, exc)
        raise
