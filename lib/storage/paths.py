from __future__ import annotations

import os
from datetime import datetime, timezone


def _utc_now(ts: datetime | None = None) -> datetime:
    return ts or datetime.now(timezone.utc)


def _date_str(ts: datetime | None = None) -> str:
    return _utc_now(ts).strftime("%Y-%m-%d")


def _time_str(ts: datetime | None = None) -> str:
    return _utc_now(ts).strftime("%H%M%S")


def _rand_hex(nbytes: int = 3) -> str:
    return os.urandom(nbytes).hex()


def _join(prefix: str, suffix: str) -> str:
    return f"{prefix.rstrip('/')}/{suffix.lstrip('/')}"


def datasets_prefix(project: str, name: str, version: str) -> str:
    return f"datasets/{project}/{name}/{version}/"


def datasets_key(project: str, name: str, version: str, filename: str) -> str:
    return _join(datasets_prefix(project, name, version), filename)


def artifacts_prefix(project: str, name: str, run_id: str) -> str:
    return f"artifacts/{project}/{name}/{run_id}/"


def artifacts_key(project: str, name: str, run_id: str, filename: str) -> str:
    return _join(artifacts_prefix(project, name, run_id), filename)


def models_prefix(project: str, name: str, version: str) -> str:
    return f"models/{project}/{name}/{version}/"


def models_key(project: str, name: str, version: str, filename: str) -> str:
    return _join(models_prefix(project, name, version), filename)


def embeddings_prefix(project: str, name: str, version: str) -> str:
    return f"embeddings/{project}/{name}/{version}/"


def embeddings_key(project: str, name: str, version: str, filename: str) -> str:
    return _join(embeddings_prefix(project, name, version), filename)


def images_prefix(project: str, name: str) -> str:
    return f"images/{project}/{name}/"


def images_key(project: str, name: str, filename: str) -> str:
    return _join(images_prefix(project, name), filename)


def telemetry_events_key(session_id: str, ts: datetime | None = None, rand: str | None = None) -> str:
    date_part = _date_str(ts)
    time_part = _time_str(ts)
    rand = rand or _rand_hex()
    return f"telemetry/events/date={date_part}/events_{session_id}_{time_part}_{rand}.jsonl.gz"


def telemetry_sessions_key(session_id: str, ts: datetime | None = None) -> str:
    date_part = _date_str(ts)
    return f"telemetry/sessions/date={date_part}/sessions_{session_id}.parquet"


def telemetry_events_glob() -> str:
    return "telemetry/events/date=*/events_*.jsonl.gz"


def telemetry_sessions_glob() -> str:
    return "telemetry/sessions/date=*/sessions_*.parquet"


def telemetry_events_parquet_prefix(date_str: str) -> str:
    return f"telemetry/events_parquet/date={date_str}"


def telemetry_events_parquet_key(date_str: str, part: str) -> str:
    return _join(telemetry_events_parquet_prefix(date_str), f"part-{part}.parquet")


def telemetry_events_parquet_manifest_key(date_str: str) -> str:
    return _join(telemetry_events_parquet_prefix(date_str), "_manifest.json")


def ops_logs_key(instance: str, ts: datetime | None = None, rand: str | None = None) -> str:
    date_part = _date_str(ts)
    time_part = _time_str(ts)
    rand = rand or _rand_hex()
    safe_instance = (instance or "unknown").replace("/", "_").replace(" ", "_")
    return f"ops/logs/date={date_part}/instance={safe_instance}/logs_{time_part}_{rand}.ndjson.gz"


def ops_sessions_key(session_id: str, ts: datetime | None = None) -> str:
    date_part = _date_str(ts)
    return f"ops/sessions/date={date_part}/session_{session_id}.json.gz"
