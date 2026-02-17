from __future__ import annotations

import os
from typing import Callable, TypeVar
from uuid import uuid4

import streamlit as st

from lib.errors.logging import log_exception
from shared.errors_ui import render_error_banner

T = TypeVar("T")


def get_app_env() -> str:
    return os.environ.get("APP_ENV", "local").strip().lower() or "local"


def is_prod_env() -> bool:
    return get_app_env() == "prod"


def _render_exception_details(exc: Exception) -> None:
    with st.expander("Error details"):
        st.exception(exc)


def _resolve_page_id(page_id: str | None) -> str:
    if page_id and page_id != "navigation":
        return page_id
    try:
        candidate = st.session_state.get("telemetry_last_page", "") or st.session_state.get("page", "")
    except Exception:
        candidate = ""
    if candidate:
        return str(candidate)
    try:
        raw = st.query_params.get("page", "")
    except Exception:
        raw = ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw) if raw else (page_id or "unknown")


def run_with_error_boundary(
    fn: Callable[[], T],
    *,
    page_id: str,
    context: dict | None = None,
) -> T | None:
    placeholder = st.empty()
    try:
        with placeholder.container():
            return fn()
    except Exception as exc:
        trace_id = getattr(exc, "_trace_id", None)
        if not trace_id:
            trace_id = uuid4().hex[:10]
            try:
                setattr(exc, "_trace_id", trace_id)
            except Exception:
                pass

        try:
            resolved_page = _resolve_page_id(page_id)
            log_exception(exc, trace_id, resolved_page, context or {})
        except Exception:
            pass

        try:
            placeholder.empty()
        except Exception:
            pass

        with placeholder.container():
            render_error_banner(trace_id)
            if not is_prod_env():
                _render_exception_details(exc)
        return None
