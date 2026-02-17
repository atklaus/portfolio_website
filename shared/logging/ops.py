from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterable

from lib.storage import io as storage_io
from lib.storage import paths as storage_paths
from lib.storage.s3_compat import get_storage_config, is_configured


_LOG_PAGE: ContextVar[str] = ContextVar("log_page", default="")
_LOG_SESSION_ID: ContextVar[str] = ContextVar("log_session_id", default="")

_CONFIGURED = False


def set_log_context(page: str | None = None, session_id: str | None = None) -> None:
    if page is not None:
        _LOG_PAGE.set(page)
    if session_id is not None:
        _LOG_SESSION_ID.set(session_id)


def _get_log_context() -> tuple[str, str]:
    return _LOG_PAGE.get(), _LOG_SESSION_ID.get()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sink_tokens(value: str | None) -> set[str]:
    if not value:
        return {"stdout"}
    return {token.strip().lower() for token in value.split("+") if token.strip()}


def _collect_redactions() -> list[str]:
    cfg = get_storage_config()
    values = [
        cfg.access_key_id,
        cfg.secret_access_key,
        cfg.bucket,
        cfg.endpoint_url,
    ]
    return [value for value in values if value]


def _sanitize_message(message: str, redactions: Iterable[str]) -> str:
    sanitized = message
    for secret in redactions:
        if secret and secret in sanitized:
            sanitized = sanitized.replace(secret, "***")
    return sanitized


class R2LogHandler(logging.Handler):
    def __init__(
        self,
        flush_records: int = 50,
        flush_seconds: int = 5,
        max_buffer: int = 500,
    ) -> None:
        super().__init__()
        self.flush_records = max(1, flush_records)
        self.flush_seconds = max(1, flush_seconds)
        self.max_buffer = max(1, max_buffer)
        self.buffer: list[dict] = []
        self.last_flush = time.time()
        self.instance = os.environ.get("FLY_ALLOC_ID") or os.environ.get("HOSTNAME") or "local"
        self.app_version = os.environ.get("APP_VERSION", "dev")
        self.git_sha = os.environ.get("GIT_SHA", "") or self.app_version
        self.redactions = _collect_redactions()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        if record.exc_info:
            try:
                exc_text = logging.Formatter().formatException(record.exc_info)
                message = f"{message}\n{exc_text}"
            except Exception:
                pass
        message = _sanitize_message(message, self.redactions)
        context_page, context_session = _get_log_context()
        page = getattr(record, "page", "") or context_page
        session_id = getattr(record, "session_id", "") or context_session
        entry = {
            "ts": _utc_now_iso(),
            "level": record.levelname,
            "message": message,
            "page": page or "",
            "session_id": session_id or "",
            "instance": self.instance,
            "app_version": self.app_version,
            "git_sha": self.git_sha,
        }
        self.buffer.append(entry)
        if len(self.buffer) > self.max_buffer:
            self.buffer.pop(0)
        now = time.time()
        if len(self.buffer) >= self.flush_records or (now - self.last_flush) >= self.flush_seconds:
            self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        try:
            payload = "\n".join(json.dumps(row, default=str) for row in self.buffer) + "\n"
            data = storage_io.gzip_bytes(payload.encode("utf-8"))
            key = storage_paths.ops_logs_key(self.instance)
            storage_io.put_bytes(
                key,
                data,
                content_type="application/x-ndjson",
                content_encoding="gzip",
            )
            self.buffer = []
            self.last_flush = time.time()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.flush()
        finally:
            super().close()


def configure_logging(log_level: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    sink_tokens = _sink_tokens(os.environ.get("LOG_SINK", "stdout"))
    root = logging.getLogger()
    level_name = log_level or os.environ.get("LOG_LEVEL", "INFO")
    root.setLevel(getattr(logging, level_name.upper(), logging.INFO))

    if "stdout" in sink_tokens and not any(
        isinstance(handler, logging.StreamHandler) for handler in root.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(handler)

    if any(token in sink_tokens for token in ("r2", "spaces", "s3")):
        if is_configured(get_storage_config()):
            if not any(isinstance(handler, R2LogHandler) for handler in root.handlers):
                handler = R2LogHandler(
                    flush_records=int(os.environ.get("LOG_FLUSH_EVENTS", "25")),
                    flush_seconds=int(os.environ.get("LOG_FLUSH_SECONDS", "5")),
                    max_buffer=int(os.environ.get("LOG_MAX_BUFFER", "1000")),
                )
                root.addHandler(handler)
        else:
            print("Warning: LOG_SINK requests object storage but R2/Spaces is not configured.")

    _CONFIGURED = True
