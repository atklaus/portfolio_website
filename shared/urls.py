from __future__ import annotations


def normalize_base_path(value: str) -> str:
    raw = (value or "").strip()
    if not raw or raw == "/":
        return ""
    if not raw.startswith("/"):
        raw = f"/{raw}"
    return raw.rstrip("/")


def app_path(path: str, base_path: str) -> str:
    normalized_base = normalize_base_path(base_path)
    raw_path = (path or "").strip()
    if not raw_path:
        raw_path = "/"
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"

    if normalized_base and (raw_path == normalized_base or raw_path.startswith(f"{normalized_base}/")):
        return raw_path

    if not normalized_base:
        return raw_path

    if raw_path == "/":
        return f"{normalized_base}/"
    return f"{normalized_base}{raw_path}"
