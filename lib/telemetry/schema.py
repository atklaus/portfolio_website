from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1

EVENT_COLUMNS = [
    "ts",
    "event_name",
    "page_id",
    "session_id",
    "trace_id",
    "event_id",
    "app_version",
    "instance_id",
    "user_agent",
    "level",
    "message",
    "schema_version",
    "payload_json",
]


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        return value
    return None


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _truncate(value: str | None, max_len: int = 512) -> str | None:
    if value is None:
        return None
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def normalize_event(raw: dict) -> dict:
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}

    ts = _first_nonempty(
        raw.get("ts"),
        raw.get("ts_utc"),
        raw.get("timestamp"),
        raw.get("time"),
        raw.get("created_at"),
    )
    ts = _to_iso(ts)

    event_name = _first_nonempty(
        raw.get("event_name"),
        raw.get("event_type"),
        raw.get("name"),
    )

    page_id = _first_nonempty(raw.get("page_id"), raw.get("page"))
    session_id = raw.get("session_id")

    trace_id = _first_nonempty(
        raw.get("trace_id"),
        payload.get("trace_id") if isinstance(payload, dict) else None,
    )

    app_version = _first_nonempty(raw.get("app_version"), raw.get("version"))
    instance_id = _first_nonempty(raw.get("instance_id"), raw.get("instance"))

    user_agent = _first_nonempty(
        raw.get("user_agent"),
        payload.get("user_agent") if isinstance(payload, dict) else None,
        payload.get("ua") if isinstance(payload, dict) else None,
    )
    user_agent = _truncate(str(user_agent)) if user_agent is not None else None

    level = _first_nonempty(raw.get("level"), payload.get("level") if isinstance(payload, dict) else None)
    message = _first_nonempty(
        raw.get("message"),
        payload.get("message") if isinstance(payload, dict) else None,
        payload.get("error") if isinstance(payload, dict) else None,
    )

    known_keys = {
        "ts",
        "ts_utc",
        "timestamp",
        "time",
        "created_at",
        "event_name",
        "event_type",
        "name",
        "page_id",
        "page",
        "session_id",
        "trace_id",
        "app_version",
        "version",
        "instance_id",
        "instance",
        "user_agent",
        "level",
        "message",
        "payload",
    }

    payload_obj: dict[str, Any] = {}
    if isinstance(payload, dict):
        payload_obj.update(payload)
    for key, value in raw.items():
        if key in known_keys:
            continue
        payload_obj[key] = value

    try:
        payload_json = json.dumps(payload_obj, default=str)
    except Exception:
        payload_json = json.dumps({"_payload": str(payload_obj)})

    event_id = None
    if ts and event_name:
        seed = "|".join(
            [
                str(ts or ""),
                str(session_id or ""),
                str(event_name or ""),
                str(page_id or ""),
                str(trace_id or ""),
            ]
        )
        payload_hash = hashlib.sha1(payload_json.encode("utf-8")).hexdigest()[:12]
        event_id = hashlib.sha1(f"{seed}|{payload_hash}".encode("utf-8")).hexdigest()

    return {
        "ts": ts,
        "event_name": str(event_name) if event_name is not None else None,
        "page_id": str(page_id) if page_id is not None else None,
        "session_id": str(session_id) if session_id is not None else None,
        "trace_id": str(trace_id) if trace_id is not None else None,
        "event_id": event_id,
        "app_version": str(app_version) if app_version is not None else None,
        "instance_id": str(instance_id) if instance_id is not None else None,
        "user_agent": user_agent,
        "level": str(level) if level is not None else None,
        "message": str(message) if message is not None else None,
        "schema_version": SCHEMA_VERSION,
        "payload_json": payload_json,
    }
