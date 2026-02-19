from __future__ import annotations

import sys
import time
import traceback
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import streamlit as st

from lib.ops.memory import log_mem
from lib.telemetry.privacy import (
    filter_allowlist,
    redact_inputs,
    truncate_structure,
)
from .config import (
    TelemetryConfig,
    get_submission_tracking,
    get_config,
)
from shared.logging.ops import set_log_context
from .session import (
    ensure_session_id,
    ensure_session_started,
    ensure_visitor_id,
    increment_error,
    increment_event,
    register_page,
    snapshot,
)
from .submission import (
    apply_redaction_rules,
    build_submission_fingerprint,
    mark_submission_if_new,
    next_submission_index,
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
    trace_id: str | None = None,
) -> None:
    config = get_config()
    if not config.enabled:
        return
    try:
        ensure_session_started()
        session_id = ensure_session_id()
        visitor_id = ensure_visitor_id()
        set_log_context(page=page, session_id=session_id)
        event = {
            "ts_utc": _utc_now_iso(),
            "session_id": session_id,
            "visitor_id": visitor_id,
            "page": page,
            "page_slug": page,
            "event_type": event_type,
            "event_name": event_type,
            "duration_ms": duration_ms,
            "payload": payload or {},
            "app_version": config.app_version,
        }
        if trace_id:
            event["trace_id"] = trace_id
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


def track_submission(
    page_id: str,
    form_id: str | None,
    inputs: dict,
    *,
    tags: dict | None = None,
) -> None:
    config = get_config()
    if not config.enabled:
        return
    page_submission_config = get_submission_tracking(page_id)
    if page_submission_config is None:
        return
    try:
        ensure_session_started()
        session_id = ensure_session_id()
        visitor_id = ensure_visitor_id()
        set_log_context(page=page_id, session_id=session_id)
        event_name = str(page_submission_config.get("event_name") or "submission")
        allowlist = page_submission_config.get("allowed_fields", [])
        redaction_rules = page_submission_config.get("redaction_rules", {})
        dedupe_window_seconds = float(page_submission_config.get("dedupe_window_seconds", 2.0))

        filtered = filter_allowlist(inputs or {}, allowlist)
        redacted = redact_inputs(filtered)
        transformed, applied_rules = apply_redaction_rules(redacted, redaction_rules)
        truncated = truncate_structure(transformed)

        fingerprint = build_submission_fingerprint(
            page_slug=page_id,
            event_name=event_name,
            form_id=form_id,
            fields=truncated,
            tags=tags,
        )
        if not mark_submission_if_new(fingerprint, dedupe_window_seconds):
            return

        submission_id = uuid4().hex
        payload: dict[str, Any] = {
            "submission_id": submission_id,
            "submission_index": next_submission_index(),
            "submitted_at": _utc_now_iso(),
            "page_slug": page_id,
            "form_id": form_id,
            "fields": truncated,
            "tags": tags or {},
            "input_fingerprint": fingerprint,
            "visitor_id": visitor_id,
        }
        if applied_rules:
            payload["redaction_rules_applied"] = applied_rules
        log_event(
            event_name,
            page_id,
            payload=payload,
            trace_id=submission_id,
        )
    except Exception as exc:
        print(f"Telemetry track_submission failed: {exc}")


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
    """Guard a page body to ensure telemetry is initialized before page rendering."""
    try:
        log_mem(f"page_start:{page}")
        instrument_page(page)
        yield
    except Exception:
        raise
    finally:
        log_mem(f"page_end:{page}")
