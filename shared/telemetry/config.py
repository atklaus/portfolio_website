from __future__ import annotations

import os
from dataclasses import dataclass

from lib.storage.s3_compat import StorageConfig, get_storage_config, is_configured


def _str_to_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool
    sink: str
    flush_events: int
    flush_seconds: int
    session_flush_seconds: int
    app_version: str
    max_buffer: int
    storage: StorageConfig


def _default_sink() -> str:
    if is_configured(get_storage_config()):
        return "stdout+r2"
    return "stdout"


def get_config() -> TelemetryConfig:
    return TelemetryConfig(
        enabled=_str_to_bool(os.environ.get("LOGGING_ENABLED"), True),
        sink=os.environ.get("LOG_SINK", _default_sink()),
        flush_events=int(os.environ.get("LOG_FLUSH_EVENTS", "25")),
        flush_seconds=int(os.environ.get("LOG_FLUSH_SECONDS", "5")),
        session_flush_seconds=int(os.environ.get("LOG_SESSION_FLUSH_SECONDS", "60")),
        app_version=os.environ.get("APP_VERSION", "dev"),
        max_buffer=int(os.environ.get("LOG_MAX_BUFFER", "1000")),
        storage=get_storage_config(),
    )


_WARNED_UNCONFIGURED = False


def warn_if_unconfigured() -> None:
    global _WARNED_UNCONFIGURED
    if _WARNED_UNCONFIGURED:
        return
    config = get_config()
    sink_flag = config.sink.lower()
    if not config.enabled:
        return
    if any(token in sink_flag for token in ("r2", "spaces", "s3")) and not is_configured(
        config.storage
    ):
        print("Warning: LOG_SINK requests object storage but R2/Spaces is not configured.")
        _WARNED_UNCONFIGURED = True


TELEMETRY_SUBMISSIONS_ENABLED_PAGES = {"wnba_success"}

TELEMETRY_SUBMISSION_ALLOWLIST = {
    "wnba_success": [
        "season",
        "college",
        "player",
        "offline_mode",
        "data_source",
        "model_version",
        "dataset_version",
    ]
}
