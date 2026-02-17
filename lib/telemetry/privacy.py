from __future__ import annotations

import json
from typing import Any


_SENSITIVE_TOKENS = ("password", "token", "secret", "auth", "email", "phone", "address")


def filter_allowlist(inputs: dict, allowlist: list[str] | None) -> dict:
    if not allowlist:
        return {}
    filtered: dict[str, Any] = {}
    for key in allowlist:
        if key in inputs:
            filtered[key] = inputs[key]
    return filtered


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _SENSITIVE_TOKENS)


def redact_inputs(inputs: dict) -> dict:
    def _redact(value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                if _is_sensitive_key(str(key)):
                    continue
                redacted[key] = _redact(item)
            return redacted
        if isinstance(value, list):
            return [_redact(item) for item in value]
        return value

    return _redact(inputs)


def truncate_structure(
    inputs: Any,
    *,
    max_str: int = 500,
    max_list: int = 50,
    max_depth: int = 6,
) -> Any:
    def _truncate(value: Any, depth: int) -> Any:
        if depth > max_depth:
            return "..."
        if isinstance(value, str):
            if len(value) <= max_str:
                return value
            return value[: max_str - 3] + "..."
        if isinstance(value, list):
            truncated = value[:max_list]
            items = [_truncate(item, depth + 1) for item in truncated]
            if len(value) > max_list:
                items.append("...")
            return items
        if isinstance(value, dict):
            return {key: _truncate(item, depth + 1) for key, item in value.items()}
        return value

    return _truncate(inputs, 0)


def dump_json_limited(obj: Any, *, max_bytes: int = 32768) -> str:
    try:
        payload = json.dumps(obj, default=str)
    except Exception:
        payload = json.dumps({"_payload": str(obj)})

    encoded = payload.encode("utf-8")
    if len(encoded) <= max_bytes:
        return payload

    wrapper_overhead = len(json.dumps({"_truncated": True, "data": ""}).encode("utf-8"))
    available = max(0, max_bytes - wrapper_overhead)
    truncated = encoded[:available].decode("utf-8", errors="ignore")
    return json.dumps({"_truncated": True, "data": truncated})
