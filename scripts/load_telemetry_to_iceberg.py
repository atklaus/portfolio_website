from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    table: str
    glob: str


def _ensure_schemas(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS r2_iceberg.raw")
    con.execute("CREATE SCHEMA IF NOT EXISTS r2_iceberg.analytics")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS r2_iceberg.raw.loaded_files (
            dataset VARCHAR,
            source_file VARCHAR,
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
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW staged_events AS
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
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW new_files AS
        SELECT DISTINCT s.source_file
        FROM staged_events s
        LEFT JOIN r2_iceberg.raw.loaded_files lf
            ON lf.dataset = ? AND lf.source_file = s.source_file
        WHERE lf.source_file IS NULL
        """,
        [spec.dataset],
    )
    file_count = con.execute("SELECT COUNT(*) FROM new_files").fetchone()[0]
    row_count = con.execute(
        """
        SELECT COUNT(*)
        FROM staged_events s
        INNER JOIN new_files nf ON nf.source_file = s.source_file
        """
    ).fetchone()[0]

    if file_count:
        con.execute(
            f"""
            INSERT INTO {spec.table}
            SELECT s.*
            FROM staged_events s
            INNER JOIN new_files nf ON nf.source_file = s.source_file
            """
        )
        con.execute(
            """
            INSERT INTO r2_iceberg.raw.loaded_files (dataset, source_file, loaded_at)
            SELECT ?, source_file, now()
            FROM new_files
            """,
            [spec.dataset],
        )

    return {"dataset": spec.dataset, "new_files": file_count, "new_rows": row_count}


def main() -> None:
    bucket = _require_env("R2_BUCKET")
    events_glob = f"s3://{bucket}/telemetry/events/date=*/**/*.parquet"
    sessions_glob = f"s3://{bucket}/telemetry/sessions/date=*/**/*.parquet"

    con = connect_iceberg()
    _ensure_schemas(con)

    events_spec = DatasetSpec(
        dataset="website_events",
        table="r2_iceberg.raw.website_events",
        glob=events_glob,
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
