from __future__ import annotations

import gzip
import io
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import boto3
import streamlit as st

from .config import TelemetryConfig
from .session import SessionSnapshot


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _date_str() -> str:
    return _utc_now().strftime("%Y-%m-%d")


def _time_str() -> str:
    return _utc_now().strftime("%H%M%S")


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

    def __post_init__(self) -> None:
        self.client = boto3.client(
            "s3",
            region_name=self.config.spaces_region or None,
            endpoint_url=self.config.spaces_endpoint or None,
            aws_access_key_id=self.config.spaces_access_key_id or None,
            aws_secret_access_key=self.config.spaces_secret_access_key or None,
        )

    def _key(self, kind: str, session_id: str, ext: str) -> str:
        prefix = self.config.spaces_prefix.rstrip("/") + "/"
        date_part = f"date={_date_str()}"
        rand = os.urandom(3).hex()
        return f"{prefix}{kind}/{date_part}/{kind}_{session_id}_{_time_str()}_{rand}.{ext}"

    def write_events(self, events: list[dict], session_id: str) -> bool:
        if not events:
            return True
        if not self.config.spaces_bucket:
            return False
        try:
            body = _json_lines_gz(events)
            key = self._key("events", session_id, "jsonl.gz")
            self.client.put_object(Bucket=self.config.spaces_bucket, Key=key, Body=body)
            return True
        except Exception as exc:
            print(f"SpacesSink events upload failed: {exc}")
            return False

    def write_session(self, snapshot: SessionSnapshot) -> bool:
        if not self.config.spaces_bucket:
            return False
        try:
            import pandas as pd
            import duckdb

            df = pd.DataFrame([snapshot.__dict__])
            parquet_buf = io.BytesIO()
            duckdb.from_df(df).write_parquet(parquet_buf)
            parquet_buf.seek(0)
            key = self._key("sessions", snapshot.session_id, "parquet")
            self.client.put_object(
                Bucket=self.config.spaces_bucket, Key=key, Body=parquet_buf.read()
            )
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

    def write_events(self, events: list[dict], session_id: str) -> bool:
        try:
            date_dir = os.path.join(self.base_dir, "events", f"date={_date_str()}")
            self._ensure_dir(date_dir)
            rand = os.urandom(3).hex()
            filename = f"events_{session_id}_{_time_str()}_{rand}.jsonl.gz"
            with open(os.path.join(date_dir, filename), "wb") as handle:
                handle.write(_json_lines_gz(events))
            return True
        except Exception:
            return False

    def write_session(self, snapshot: SessionSnapshot) -> bool:
        try:
            import pandas as pd

            date_dir = os.path.join(self.base_dir, "sessions", f"date={_date_str()}")
            self._ensure_dir(date_dir)
            filename = f"sessions_{_time_str()}.parquet"
            df = pd.DataFrame([snapshot.__dict__])
            df.to_parquet(os.path.join(date_dir, filename), index=False)
            return True
        except Exception:
            return False


def build_sinks(config: TelemetryConfig) -> list[BaseSink]:
    sink_flag = config.sink.lower()
    sinks: list[BaseSink] = []
    if "stdout" in sink_flag:
        sinks.append(StdoutSink())
    if "spaces" in sink_flag:
        if (
            config.spaces_bucket
            and config.spaces_access_key_id
            and config.spaces_secret_access_key
        ):
            sinks.append(SpacesSink(config))
        else:
            print("SpacesSink disabled due to missing credentials.")
    if "local" in sink_flag:
        sinks.append(LocalSink())
    return sinks
