from __future__ import annotations

import hashlib
import json
import os
import time
from bisect import bisect_right
from typing import Any

import streamlit as st


def _state() -> dict:
    return st.session_state


def _to_jsonable(value: Any) -> str:
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except Exception:
        return str(value)


def _hash_value(value: Any) -> str:
    salt = os.environ.get("TELEMETRY_HASH_SALT", "")
    payload = f"{salt}|{_to_jsonable(value)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bucketize_value(value: Any, bins: list[float], labels: list[str] | None) -> Any:
    try:
        numeric = float(value)
    except Exception:
        return value
    if not bins:
        return numeric
    idx = bisect_right(bins, numeric)
    if labels and len(labels) == len(bins) + 1:
        return labels[idx]
    if idx == 0:
        return f"<= {bins[0]}"
    if idx >= len(bins):
        return f"> {bins[-1]}"
    return f"({bins[idx - 1]}, {bins[idx]}]"


def apply_redaction_rules(
    inputs: dict[str, Any],
    redaction_rules: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    sanitized: dict[str, Any] = {}
    applied: dict[str, str] = {}
    for key, value in inputs.items():
        raw_rule = redaction_rules.get(key, "keep")
        if isinstance(raw_rule, str):
            action = raw_rule.strip().lower()
            options: dict[str, Any] = {}
        elif isinstance(raw_rule, dict):
            action = str(raw_rule.get("action", "keep")).strip().lower()
            options = raw_rule
        else:
            action = "keep"
            options = {}

        if action in {"", "keep"}:
            sanitized[key] = value
            continue
        if action == "drop":
            applied[key] = "drop"
            continue
        if action == "hash":
            sanitized[key] = _hash_value(value)
            applied[key] = "hash"
            continue
        if action == "bucketize":
            bins = options.get("bins", [])
            labels = options.get("labels")
            if isinstance(bins, list):
                bins = [float(item) for item in bins]
            else:
                bins = []
            labels_list = labels if isinstance(labels, list) else None
            sanitized[key] = _bucketize_value(value, bins=bins, labels=labels_list)
            applied[key] = "bucketize"
            continue

        sanitized[key] = value
    return sanitized, applied


def build_submission_fingerprint(
    page_slug: str,
    event_name: str,
    form_id: str | None,
    fields: dict[str, Any],
    tags: dict[str, Any] | None,
) -> str:
    payload = {
        "page_slug": page_slug,
        "event_name": event_name,
        "form_id": form_id,
        "fields": fields,
        "tags": tags or {},
    }
    canonical = _to_jsonable(payload)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def mark_submission_if_new(fingerprint: str, dedupe_window_seconds: float) -> bool:
    now = time.time()
    state = _state()
    seen = state.get("telemetry_recent_submission_fingerprints")
    if not isinstance(seen, dict):
        seen = {}

    # Bound memory and keep only recent fingerprints.
    keep_after = now - max(float(dedupe_window_seconds), 2.0) * 120
    pruned = {
        key: ts
        for key, ts in seen.items()
        if isinstance(ts, (float, int)) and float(ts) >= keep_after
    }

    previous = pruned.get(fingerprint)
    if previous is not None and (now - float(previous)) <= float(dedupe_window_seconds):
        state["telemetry_recent_submission_fingerprints"] = pruned
        return False

    pruned[fingerprint] = now
    state["telemetry_recent_submission_fingerprints"] = pruned
    return True


def next_submission_index() -> int:
    state = _state()
    index = int(state.get("telemetry_submission_count", 0)) + 1
    state["telemetry_submission_count"] = index
    return index
