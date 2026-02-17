from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import duckdb
import pandas as pd

from lib.storage import io as storage_io
from lib.storage import paths as storage_paths
from lib.storage.s3_compat import get_bucket, get_client, get_storage_config, is_configured
from lib.telemetry.schema import EVENT_COLUMNS, SCHEMA_VERSION, normalize_event


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _date_range(days_back: int) -> list[date]:
    today = datetime.now(timezone.utc).date()
    return [today - timedelta(days=offset) for offset in range(days_back)]


def _list_keys(prefix: str, max_files: int) -> list[str]:
    client = get_client()
    bucket = get_bucket()
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if not key:
                continue
            keys.append(key)
            if len(keys) >= max_files:
                return keys
    return keys


def _delete_prefix(prefix: str) -> None:
    client = get_client()
    bucket = get_bucket()
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if key:
                keys.append({"Key": key})
            if len(keys) == 1000:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
                keys = []
    if keys:
        client.delete_objects(Bucket=bucket, Delete={"Objects": keys})


def _iter_event_records(keys: Iterable[str]) -> Iterator[dict]:
    client = get_client()
    bucket = get_bucket()
    for key in keys:
        response = client.get_object(Bucket=bucket, Key=key)
        try:
            body = response["Body"].read()
        except Exception as exc:
            print(f"Skipping {key} due to read error: {exc}")
            continue
        try:
            data = gzip.decompress(body)
        except Exception:
            data = body
        stream = io.BytesIO(data)
        for line in stream:
            if not line:
                continue
            try:
                raw = json.loads(line)
            except Exception:
                continue
            if isinstance(raw, dict):
                yield raw


def _write_part(rows: list[dict], key: str) -> None:
    df = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    con = duckdb.connect()
    con.register("events_df", df)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as handle:
        tmp_path = handle.name
    try:
        con.execute(f"COPY events_df TO '{tmp_path}' (FORMAT PARQUET, COMPRESSION 'zstd')")
        storage_io.put_file(key, tmp_path, content_type="application/x-parquet")
    finally:
        con.close()
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def _write_manifest(date_str: str, row_count: int, file_count: int) -> None:
    manifest = {
        "date": date_str,
        "generated_at": _utc_now_iso(),
        "schema_version": SCHEMA_VERSION,
        "row_count": row_count,
        "file_count": file_count,
    }
    payload = json.dumps(manifest, default=str).encode("utf-8")
    key = storage_paths.telemetry_events_parquet_manifest_key(date_str)
    storage_io.put_bytes(key, payload, content_type="application/json")


def build_for_date(
    date_str: str,
    max_files: int,
    output_chunk_rows: int,
    dry_run: bool,
) -> None:
    prefix = f"telemetry/events/date={date_str}/"
    keys = _list_keys(prefix, max_files)
    if not keys:
        print(f"No events found for {date_str}")
        return

    print(f"{date_str}: processing {len(keys)} event objects")
    if dry_run:
        return

    parquet_prefix = storage_paths.telemetry_events_parquet_prefix(date_str)
    _delete_prefix(parquet_prefix)

    part_index = 0
    row_count = 0
    buffer: list[dict] = []

    for raw in _iter_event_records(keys):
        normalized = normalize_event(raw)
        buffer.append(normalized)
        if len(buffer) >= output_chunk_rows:
            part_key = storage_paths.telemetry_events_parquet_key(date_str, f"{part_index:04d}")
            _write_part(buffer, part_key)
            row_count += len(buffer)
            part_index += 1
            buffer = []

    if buffer:
        part_key = storage_paths.telemetry_events_parquet_key(date_str, f"{part_index:04d}")
        _write_part(buffer, part_key)
        row_count += len(buffer)
        part_index += 1

    _write_manifest(date_str, row_count=row_count, file_count=part_index)
    print(f"{date_str}: wrote {part_index} parquet parts ({row_count} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build telemetry events parquet partitions.")
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD date to build")
    parser.add_argument("--days-back", type=int, default=2)
    parser.add_argument("--max-files-per-day", type=int, default=2000)
    parser.add_argument("--output-chunk-rows", type=int, default=50000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = get_storage_config()
    if not is_configured(config):
        raise RuntimeError("Storage is not configured. Set R2/Spaces credentials.")

    if args.date:
        target_dates = [_parse_date(args.date)]
    else:
        target_dates = _date_range(args.days_back)

    for target in sorted(target_dates):
        build_for_date(
            target.isoformat(),
            max_files=args.max_files_per_day,
            output_chunk_rows=args.output_chunk_rows,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
