from __future__ import annotations

import datetime as dt
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.duckdb_iceberg import connect_iceberg
from lib.storage.s3_compat import get_bucket, get_client


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


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


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


def _has_any_parquet_files(con, globs: tuple[str, ...]) -> bool:
    return any(_has_parquet_files(con, glob) for glob in globs)


def _list_parquet_objects(prefix: str) -> list[tuple[str, str, int, dt.datetime | None]]:
    """Return object metadata for parquet files under an S3/R2 prefix.

    Used for idempotency when parquet keys may be overwritten in-place.
    We treat (source_file, etag) as the load key.
    """
    client = get_client()
    bucket = get_bucket()

    rows: list[tuple[str, str, int, dt.datetime | None]] = []
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
            rows.append((f"s3://{bucket}/{key}", etag, size, last_modified))

    return rows


def _list_parquet_objects_many(prefixes: tuple[str, ...]) -> list[tuple[str, str, int, dt.datetime | None]]:
    rows: list[tuple[str, str, int, dt.datetime | None]] = []
    for prefix in prefixes:
        rows.extend(_list_parquet_objects(prefix))
    return rows


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_column_info(con, table: str) -> list[tuple[str, str]]:
    return [(str(row[1]), str(row[2])) for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()]


def _table_columns(con, table: str) -> list[str]:
    return [name for name, _ in _table_column_info(con, table)]


def _view_columns(con, view: str) -> list[str]:
    return [str(row[0]) for row in con.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()]


def _insert_compatible_rows(con, table: str, view: str, new_files_view: str) -> None:
    """Insert rows using only the intersection of table/view columns.

    Iceberg table evolution via ALTER TABLE ADD COLUMN is not consistently available
    across DuckDB versions/catalog integrations. This keeps ingestion resilient when
    staged parquet adds new columns.
    """
    table_info = _table_column_info(con, table)
    table_cols = [name for name, _ in table_info]
    staged_cols = _view_columns(con, view)
    staged_set = set(staged_cols)
    insert_cols = [col for col in table_cols if col in staged_set]

    if not insert_cols:
        raise RuntimeError(
            f"No compatible columns found for insert into {table}; "
            f"table_cols={table_cols}, staged_cols={staged_cols}"
        )

    dropped_staged_cols = [col for col in staged_cols if col not in set(table_cols)]
    if dropped_staged_cols:
        print(
            f"{table}: staged columns not present in target schema; "
            f"skipping {len(dropped_staged_cols)} column(s): {dropped_staged_cols}"
        )

    insert_cols_sql = ", ".join(_quote_ident(col) for col in insert_cols)
    type_lookup = {name: col_type for name, col_type in table_info}
    select_cols_sql = ", ".join(
        f"try_cast(s.{_quote_ident(col)} as {type_lookup[col]}) as {_quote_ident(col)}"
        for col in insert_cols
    )
    con.execute(
        f"""
        INSERT INTO {table} ({insert_cols_sql})
        SELECT {select_cols_sql}
        FROM {view} s
        INNER JOIN {new_files_view} nf ON nf.source_file = s.source_file
        """
    )


def _split_table_name(table: str) -> tuple[str, str, str]:
    parts = table.split(".")
    if len(parts) != 3:
        raise ValueError(f"Expected catalog.schema.table format, got: {table}")
    return parts[0], parts[1], parts[2]


def _table_exists(con, table: str) -> bool:
    catalog, schema, name = _split_table_name(table)
    dotted_schema = f"{catalog}.{schema}"

    checks: list[tuple[str, list[str]]] = [
        (
            """
            SELECT 1
            FROM duckdb_tables()
            WHERE table_name = ?
              AND (
                (database_name = ? AND schema_name = ?)
                OR schema_name = ?
              )
            LIMIT 1
            """,
            [name, catalog, schema, dotted_schema],
        ),
        (
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = ?
              AND (
                (table_catalog = ? AND table_schema = ?)
                OR table_schema = ?
              )
            LIMIT 1
            """,
            [name, catalog, schema, dotted_schema],
        ),
        (
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = ? AND table_schema = ?
            LIMIT 1
            """,
            [name, schema],
        ),
    ]

    for sql, params in checks:
        try:
            row = con.execute(sql, params).fetchone()
            if row is not None:
                return True
        except Exception:
            continue
    return False


def _normalize_iceberg_type(type_name: str) -> str:
    upper = type_name.strip().upper()
    primitive = {
        "BOOLEAN",
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "REAL",
        "DOUBLE",
        "VARCHAR",
        "DATE",
        "TIMESTAMP",
        "TIME",
        "BLOB",
    }
    if upper in primitive:
        return upper
    if upper.startswith("DECIMAL("):
        return upper
    if "TIMESTAMP WITH TIME ZONE" in upper:
        return "TIMESTAMP"
    # Iceberg + DuckDB can reject some complex types during CREATE TABLE.
    if any(token in upper for token in ("STRUCT", "MAP", "LIST", "ARRAY", "UNION", "JSON")):
        return "VARCHAR"
    return "VARCHAR"


def _staged_schema_sql(globs: tuple[str, ...]) -> str:
    if not globs:
        raise RuntimeError("Expected at least one parquet glob.")
    glob_list_sql = ", ".join(f"'{_sql_escape(glob)}'" for glob in globs)
    return (
        "SELECT * EXCLUDE (filename), filename AS source_file, now() AS ingested_at "
        f"FROM read_parquet([{glob_list_sql}], "
        "hive_partitioning=true, filename=true, union_by_name=true)"
    )


def _safe_temp_name(base: str, dataset: str) -> str:
    suffix = "".join(ch if ch.isalnum() else "_" for ch in dataset.lower())
    return f"{base}_{suffix}"


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    table: str
    globs: tuple[str, ...]
    prefixes: tuple[str, ...]


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


def _create_raw_table(con, table: str, globs: tuple[str, ...]) -> None:
    if _table_exists(con, table):
        return

    schema_rows = con.execute(f"DESCRIBE {_staged_schema_sql(globs)} LIMIT 0").fetchall()
    if not schema_rows:
        raise RuntimeError(f"Unable to infer staged schema for {table} from globs={globs}")

    seen: set[str] = set()
    column_defs: list[str] = []
    for row in schema_rows:
        col_name = str(row[0])
        if col_name in seen:
            continue
        seen.add(col_name)
        col_type = _normalize_iceberg_type(str(row[1]))
        column_defs.append(f"{_quote_ident(col_name)} {col_type}")

    if not column_defs:
        raise RuntimeError(f"No columns inferred for {table}")

    con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(column_defs)})")


def _load_dataset(con, spec: DatasetSpec) -> dict[str, Any]:
    dataset_literal = _sql_escape(spec.dataset)
    staged_rows_view = _safe_temp_name("staged_rows", spec.dataset)
    file_meta_table = _safe_temp_name("file_meta", spec.dataset)
    file_meta_dedup_view = _safe_temp_name("file_meta_dedup", spec.dataset)
    new_files_view = _safe_temp_name("new_files", spec.dataset)

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW {staged_rows_view} AS
        {_staged_schema_sql(spec.globs)}
        """
    )

    meta_rows = _list_parquet_objects_many(spec.prefixes)
    if not meta_rows:
        return {
            "dataset": spec.dataset,
            "source_files": 0,
            "new_files": 0,
            "new_rows": 0,
            "total_rows": 0,
        }

    con.execute(f"DROP TABLE IF EXISTS {file_meta_table}")
    con.execute(
        f"""
        CREATE TEMP TABLE {file_meta_table} (
            source_file VARCHAR,
            etag VARCHAR,
            size_bytes BIGINT,
            last_modified TIMESTAMP
        )
        """
    )
    con.executemany(
        f"""
        INSERT INTO {file_meta_table} (source_file, etag, size_bytes, last_modified)
        VALUES (?, ?, ?, ?)
        """,
        meta_rows,
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW {file_meta_dedup_view} AS
        SELECT
            source_file,
            etag,
            size_bytes,
            last_modified
        FROM (
            SELECT
                *,
                row_number() over (
                    partition by source_file, coalesce(etag, '')
                    order by coalesce(last_modified, TIMESTAMP '1970-01-01') desc
                ) as rn
            FROM {file_meta_table}
        )
        WHERE rn = 1
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW {new_files_view} AS
        SELECT DISTINCT fm.source_file, fm.etag, fm.size_bytes, fm.last_modified
        FROM {file_meta_dedup_view} fm
        LEFT JOIN r2_iceberg.raw.loaded_files lf
          ON lf.dataset = '{dataset_literal}'
         AND lf.source_file = fm.source_file
         AND coalesce(lf.etag, '') = coalesce(fm.etag, '')
        WHERE lf.source_file IS NULL
        """
    )

    file_count = con.execute(f"SELECT COUNT(*) FROM {new_files_view}").fetchone()[0]
    row_count = con.execute(
        f"""
        SELECT COUNT(*)
        FROM {staged_rows_view} s
        INNER JOIN {new_files_view} nf ON nf.source_file = s.source_file
        """
    ).fetchone()[0]

    if file_count:
        _insert_compatible_rows(con, spec.table, staged_rows_view, new_files_view)

        con.execute(
            f"""
            INSERT INTO r2_iceberg.raw.loaded_files (
              dataset, source_file, etag, size_bytes, last_modified, loaded_at
            )
            SELECT ?, source_file, etag, size_bytes, last_modified, now()
            FROM {new_files_view}
            """,
            [spec.dataset],
        )

    total_rows = con.execute(f"SELECT COUNT(*) FROM {spec.table}").fetchone()[0]
    return {
        "dataset": spec.dataset,
        "source_files": int(len(meta_rows)),
        "new_files": int(file_count),
        "new_rows": int(row_count),
        "total_rows": int(total_rows),
    }


def main() -> None:
    bucket = _require_env("R2_BUCKET")

    def _parse_prefixes(var_name: str, default_prefixes: tuple[str, ...]) -> tuple[str, ...]:
        raw = _get_env(var_name, "")
        if not raw:
            return default_prefixes
        prefixes = tuple(part.strip() for part in raw.split(",") if part.strip())
        return prefixes or default_prefixes

    events_prefixes = _parse_prefixes(
        "TELEMETRY_EVENTS_PARQUET_PREFIXES",
        (_get_env("TELEMETRY_EVENTS_PARQUET_PREFIX", "telemetry/events_parquet/"),),
    )
    sessions_prefixes = _parse_prefixes(
        "TELEMETRY_SESSIONS_PARQUET_PREFIXES",
        (
            _get_env("TELEMETRY_SESSIONS_PARQUET_PREFIX", "telemetry/sessions/"),
            "telemetry/sessions_parquet/",
        ),
    )

    events_globs = tuple(f"s3://{bucket}/{prefix}date=*/**/*.parquet" for prefix in events_prefixes)
    sessions_globs = tuple(f"s3://{bucket}/{prefix}date=*/**/*.parquet" for prefix in sessions_prefixes)

    con = connect_iceberg()

    import duckdb

    print(f"duckdb_version={duckdb.__version__}")
    print(f"events_prefixes={events_prefixes}")
    print(f"sessions_prefixes={sessions_prefixes}")

    _ensure_schemas(con)

    events_spec = DatasetSpec(
        dataset="website_events",
        table="r2_iceberg.raw.website_events",
        globs=events_globs,
        prefixes=events_prefixes,
    )

    if not _has_any_parquet_files(con, events_spec.globs):
        print("No event parquet files found; exiting.")
        return

    _create_raw_table(con, events_spec.table, events_spec.globs)
    events_result = _load_dataset(con, events_spec)
    print(
        "events_load "
        f"source_files={events_result['source_files']} "
        f"new_files={events_result['new_files']} "
        f"new_rows={events_result['new_rows']} "
        f"table_rows={events_result['total_rows']}"
    )

    sessions_result = None
    if _has_any_parquet_files(con, sessions_globs):
        sessions_spec = DatasetSpec(
            dataset="website_sessions",
            table="r2_iceberg.raw.website_sessions",
            globs=sessions_globs,
            prefixes=sessions_prefixes,
        )
        _create_raw_table(con, sessions_spec.table, sessions_spec.globs)
        sessions_result = _load_dataset(con, sessions_spec)
        print(
            "sessions_load "
            f"source_files={sessions_result['source_files']} "
            f"new_files={sessions_result['new_files']} "
            f"new_rows={sessions_result['new_rows']} "
            f"table_rows={sessions_result['total_rows']}"
        )
    else:
        print("No session parquet files found; skipping sessions load.")

    print("Telemetry Iceberg load complete.")
    print(events_result)
    if sessions_result:
        print(sessions_result)


if __name__ == "__main__":
    main()
