from __future__ import annotations

import gzip
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime

from lib.storage import io as storage_io
from lib.storage import paths as storage_paths
from lib.storage.s3_compat import is_configured

from .config import TelemetryConfig
from .session import SessionSnapshot


def _json_lines(events: list[dict]) -> bytes:
    lines = [json.dumps(event, default=str) for event in events]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _json_lines_gz(events: list[dict]) -> bytes:
    payload = _json_lines(events)
    return gzip.compress(payload)


class BaseSink:
    def write_events(self, events: list[dict], session_id: str) -> bool:
        raise NotImplementedError

    def write_session(self, snapshot: SessionSnapshot) -> bool:
        return True


class StdoutSink(BaseSink):
    def write_events(self, events: list[dict], session_id: str) -> bool:
        try:
            payload = _json_lines(events).decode("utf-8")
            print(payload)
            return True
        except Exception:
            return False


@dataclass
class SpacesSink(BaseSink):
    config: TelemetryConfig

    def write_events(self, events: list[dict], session_id: str) -> bool:
        if not events:
            return True
        if not is_configured(self.config.storage):
            return False
        try:
            body = _json_lines_gz(events)
            key = storage_paths.telemetry_events_key(session_id)
            storage_io.put_bytes(
                key,
                body,
                content_type="application/x-ndjson",
                content_encoding="gzip",
            )
            return True
        except Exception as exc:
            print(f"SpacesSink events upload failed: {exc}")
            return False

    def write_session(self, snapshot: SessionSnapshot) -> bool:
        if not is_configured(self.config.storage):
            return False
        try:
            import duckdb

            relation = duckdb.values([tuple(snapshot.__dict__.values())], list(snapshot.__dict__.keys()))
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as handle:
                tmp_path = handle.name
            relation.write_parquet(tmp_path)
            try:
                ts = datetime.fromisoformat(snapshot.ts_utc)
            except Exception:
                ts = None
            key = storage_paths.telemetry_sessions_key(snapshot.session_id, ts=ts)
            storage_io.put_file(
                key,
                tmp_path,
                content_type="application/x-parquet",
            )
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return True
        except Exception as exc:
            print(f"SpacesSink session upload failed: {exc}")
            return False


class LocalSink(BaseSink):
    def __init__(self, base_dir: str = "data/logs") -> None:
        self.base_dir = base_dir

    def _ensure_dir(self, path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass

    def _local_path(self, key: str) -> str:
        normalized = key.lstrip("/")
        if normalized.startswith("telemetry/"):
            normalized = normalized[len("telemetry/") :]
        return os.path.join(self.base_dir, normalized)

    def write_events(self, events: list[dict], session_id: str) -> bool:
        try:
            key = storage_paths.telemetry_events_key(session_id)
            path = self._local_path(key)
            self._ensure_dir(os.path.dirname(path))
            with open(path, "wb") as handle:
                handle.write(_json_lines_gz(events))
            return True
        except Exception:
            return False

    def write_session(self, snapshot: SessionSnapshot) -> bool:
        try:
            import pandas as pd

            try:
                ts = datetime.fromisoformat(snapshot.ts_utc)
            except Exception:
                ts = None
            key = storage_paths.telemetry_sessions_key(snapshot.session_id, ts=ts)
            path = self._local_path(key)
            self._ensure_dir(os.path.dirname(path))
            df = pd.DataFrame([snapshot.__dict__])
            df.to_parquet(path, index=False)
            return True
        except Exception:
            return False


def build_sinks(config: TelemetryConfig) -> list[BaseSink]:
    sink_flag = config.sink.lower()
    sinks: list[BaseSink] = []
    if "stdout" in sink_flag:
        sinks.append(StdoutSink())
    if any(token in sink_flag for token in ("spaces", "r2", "s3")):
        if is_configured(config.storage):
            sinks.append(SpacesSink(config))
        else:
            print("SpacesSink disabled due to missing credentials.")
    if "local" in sink_flag:
        sinks.append(LocalSink())
    return sinks
