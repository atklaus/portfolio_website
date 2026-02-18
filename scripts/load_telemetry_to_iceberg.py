from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import datetime as dt

import pandas as pd

from lib.storage.s3_compat import get_client, get_bucket

from lib.duckdb_iceberg import connect_iceberg


def _get_env(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value:
        return value
    return default


def _require_env(key: str) -> str:
    value = _get_env(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def _has_parquet_files(con, glob: str) -> bool:
    try:
        con.execute(
            """
            SELECT 1
            FROM read_parquet(?,
                hive_partitioning=true,
                filename=true,
                union_by_name=true
            )
            LIMIT 1
            """,
            [glob],
        ).fetchone()
        return True
    except Exception as exc:
        if "no files found" in str(exc).lower():
            return False
        raise


# Helper: List parquet objects with etag and metadata
def _list_parquet_objects(prefix: str) -> pd.DataFrame:
    """Return object metadata for parquet files under an S3/R2 prefix.

    This is used for idempotency when parquet files are overwritten in-place
    (same key, new ETag). We treat (source_file, etag) as the load key.
    """
    client = get_client()
    bucket = get_bucket()

    rows: list[dict[str, Any]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if not key or not key.endswith(".parquet"):
                continue
            etag = (item.get("ETag") or "").strip('"')
            last_modified = item.get("LastModified")
            if isinstance(last_modified, dt.datetime):
                last_modified = last_modified.replace(tzinfo=dt.timezone.utc)
            size = int(item.get("Size") or 0)
            rows.append(
                {
                    "source_file": f"s3://{bucket}/{key}",
                    "etag": etag,
                    "last_modified": last_modified,
                    "size_bytes": size,
                }
            )

    return pd.DataFrame(rows)


# Helper: Ensure table columns exist for all columns in the staged view
def _ensure_table_columns(con, table: str, view: str) -> None:
    """Add missing columns to `table` based on `view` schema.

    DuckDB will error if you try to insert columns that don't exist.
    We compare view columns to table columns and ALTER TABLE to add any missing.
    """
    table_cols = {
        row[1]: row[2]
        for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
    }

    # DuckDB supports DESCRIBE SELECT ...
    view_desc = con.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()
    view_cols = [(row[0], row[1]) for row in view_desc]

    for col_name, col_type in view_cols:
        if col_name in table_cols:
            continue
        # Be conservative with quoted identifiers
        con.execute(f'ALTER TABLE {table} ADD COLUMN "{col_name}" {col_type}')



@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    table: str
    glob: str
    prefix: str


def _ensure_schemas(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS r2_iceberg.raw")
    con.execute("CREATE SCHEMA IF NOT EXISTS r2_iceberg.analytics")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS r2_iceberg.raw.loaded_files (
            dataset VARCHAR,
            source_file VARCHAR,
            etag VARCHAR,
            size_bytes BIGINT,
            last_modified TIMESTAMP,
            loaded_at TIMESTAMP
        )
        """
    )


def _create_raw_table(con, table: str, glob: str) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} AS
        SELECT
            * EXCLUDE (filename),
            filename AS source_file,
            now() AS ingested_at
        FROM read_parquet(?,
            hive_partitioning=true,
            filename=true,
            union_by_name=true
        )
        LIMIT 0
        """,
        [glob],
    )



def _load_dataset(con, spec: DatasetSpec) -> dict[str, Any]:
    # Stage all rows from parquet
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW staged_rows AS
        SELECT
            * EXCLUDE (filename),
            filename AS source_file,
            now() AS ingested_at
        FROM read_parquet(?,
            hive_partitioning=true,
            filename=true,
            union_by_name=true
        )
        """,
        [spec.glob],
    )

    # File metadata for idempotency (handles overwritten parquet keys)
    meta_df = _list_parquet_objects(spec.prefix)
    if meta_df.empty:
        return {"dataset": spec.dataset, "new_files": 0, "new_rows": 0}

    con.register("file_meta_df", meta_df)
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW file_meta AS
        SELECT
            source_file,
            etag,
            size_bytes,
            last_modified
        FROM file_meta_df
        """
    )

    # Identify new (file, etag) pairs
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW new_files AS
        SELECT DISTINCT fm.source_file, fm.etag, fm.size_bytes, fm.last_modified
        FROM file_meta fm
        LEFT JOIN r2_iceberg.raw.loaded_files lf
          ON lf.dataset = ?
         AND lf.source_file = fm.source_file
         AND coalesce(lf.etag, '') = coalesce(fm.etag, '')
        WHERE lf.source_file IS NULL
        """,
        [spec.dataset],
    )

    file_count = con.execute("SELECT COUNT(*) FROM new_files").fetchone()[0]
    row_count = con.execute(
        """
        SELECT COUNT(*)
        FROM staged_rows s
        INNER JOIN new_files nf ON nf.source_file = s.source_file
        """
    ).fetchone()[0]

    if file_count:
        # Ensure target table can accept any evolved columns
        _ensure_table_columns(con, spec.table, "staged_rows")

        # Insert BY NAME to avoid column-order issues. Extra columns in target
        # will receive NULL if absent in the source.
        con.execute(
            f"""
            INSERT INTO {spec.table} BY NAME
            SELECT s.*
            FROM staged_rows s
            INNER JOIN new_files nf ON nf.source_file = s.source_file
            """
        )

        con.execute(
            """
            INSERT INTO r2_iceberg.raw.loaded_files (
              dataset, source_file, etag, size_bytes, last_modified, loaded_at
            )
            SELECT ?, source_file, etag, size_bytes, last_modified, now()
            FROM new_files
            """,
            [spec.dataset],
        )

    return {"dataset": spec.dataset, "new_files": int(file_count), "new_rows": int(row_count)}


def main() -> None:
    bucket = _require_env("R2_BUCKET")
    events_prefix = _get_env("TELEMETRY_EVENTS_PARQUET_PREFIX", "telemetry/events_parquet/")
    sessions_prefix = _get_env("TELEMETRY_SESSIONS_PARQUET_PREFIX", "telemetry/sessions_parquet/")

    # Glob for parquet parts under hive partitions like date=YYYY-MM-DD
    events_glob = f"s3://{bucket}/{events_prefix}date=*/**/*.parquet"
    sessions_glob = f"s3://{bucket}/{sessions_prefix}date=*/**/*.parquet"

    con = connect_iceberg()
    import duckdb

    print(f"duckdb_version={duckdb.__version__}")
    _ensure_schemas(con)

    events_spec = DatasetSpec(
        dataset="website_events",
        table="r2_iceberg.raw.website_events",
        glob=events_glob,
        prefix=f"{events_prefix}date=",
    )
    if not _has_parquet_files(con, events_spec.glob):
        print("No event parquet files found; exiting.")
        return

    _create_raw_table(con, events_spec.table, events_spec.glob)
    events_result = _load_dataset(con, events_spec)

    sessions_result = None
    if _has_parquet_files(con, sessions_glob):
        sessions_spec = DatasetSpec(
            dataset="website_sessions",
            table="r2_iceberg.raw.website_sessions",
            glob=sessions_glob,
            prefix=f"{sessions_prefix}date=",
        )
        _create_raw_table(con, sessions_spec.table, sessions_spec.glob)
        sessions_result = _load_dataset(con, sessions_spec)
    else:
        print("No session parquet files found; skipping sessions load.")

    print("Telemetry Iceberg load complete.")
    print(events_result)
    if sessions_result:
        print(sessions_result)


if __name__ == "__main__":
    main()
