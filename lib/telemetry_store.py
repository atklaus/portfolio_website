from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from lib.storage.s3_compat import duckdb_httpfs_config, get_storage_config, is_configured


def _get_secret(key: str) -> str:
    value = os.environ.get(key)
    if value:
        return value
    try:
        import streamlit as st

        if key in st.secrets:
            secret_val = st.secrets.get(key, "")
            return str(secret_val) if secret_val is not None else ""
    except Exception:
        pass
    return ""


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _duckdb_httpfs_from_env() -> dict[str, Any]:
    account_id = _get_secret("R2_ACCOUNT_ID")
    access_key = _get_secret("R2_ACCESS_KEY_ID")
    secret_key = _get_secret("R2_SECRET_ACCESS_KEY")
    if not (account_id and access_key and secret_key):
        return {}
    return {
        "s3_region": "auto",
        "s3_endpoint": f"{account_id}.r2.cloudflarestorage.com",
        "s3_access_key_id": access_key,
        "s3_secret_access_key": secret_key,
        "s3_url_style": "path",
        "s3_use_ssl": True,
    }


@dataclass(frozen=True)
class OverviewResult:
    source: str
    sessions: int | None
    pageviews: int | None
    events: int | None
    errors: int | None
    sessions_daily: Any
    pageviews_daily: Any


class TelemetryStore:
    def __init__(self, storage_config=None) -> None:
        self._storage_config = storage_config or get_storage_config()
        self._bucket = _first_nonempty(
            _get_secret("R2_BUCKET"),
            self._storage_config.bucket,
        )
        self._iceberg_con = None
        self._iceberg_error: Exception | None = None
        self._parquet_con = None

    def _events_glob(self) -> str:
        if not self._bucket:
            raise RuntimeError("Telemetry bucket is not configured.")
        return f"s3://{self._bucket}/telemetry/events/date=*/**/*.parquet"

    def _ensure_parquet_con(self):
        if self._parquet_con is not None:
            return self._parquet_con
        import duckdb

        con = duckdb.connect()
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        httpfs_items = (
            duckdb_httpfs_config(self._storage_config)
            if is_configured(self._storage_config)
            else _duckdb_httpfs_from_env()
        )
        for key, value in httpfs_items.items():
            if value in ("", None):
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            con.execute(f"SET {key}='{value}'")
        self._parquet_con = con
        return con

    def _ensure_iceberg_con(self):
        if self._iceberg_con is not None:
            return self._iceberg_con
        if self._iceberg_error is not None:
            raise self._iceberg_error
        try:
            from lib.duckdb_iceberg import connect_iceberg

            self._iceberg_con = connect_iceberg()
            return self._iceberg_con
        except Exception as exc:
            self._iceberg_error = exc
            raise

    def iceberg_available(self) -> bool:
        try:
            self._ensure_iceberg_con()
            return True
        except Exception:
            return False

    def _iceberg_table_exists(self, schema: str, table: str) -> bool:
        try:
            con = self._ensure_iceberg_con()
            row = con.execute(
                """
                SELECT 1
                FROM r2_iceberg.information_schema.tables
                WHERE table_schema = ? AND table_name = ?
                """,
                [schema, table],
            ).fetchone()
            return row is not None
        except Exception:
            return False

    def ingestion_status(self) -> dict[str, Any] | None:
        if not self.iceberg_available():
            return None
        try:
            con = self._ensure_iceberg_con()
            events_rows, events_last = con.execute(
                """
                SELECT COUNT(*) AS rows, MAX(ingested_at) AS last_ingested_at
                FROM r2_iceberg.raw.website_events
                """
            ).fetchone()
            sessions_rows = None
            sessions_last = None
            if self._iceberg_table_exists("raw", "website_sessions"):
                sessions_rows, sessions_last = con.execute(
                    """
                    SELECT COUNT(*) AS rows, MAX(ingested_at) AS last_ingested_at
                    FROM r2_iceberg.raw.website_sessions
                    """
                ).fetchone()
            return {
                "events_rows": events_rows,
                "events_last_ingested_at": events_last,
                "sessions_rows": sessions_rows,
                "sessions_last_ingested_at": sessions_last,
            }
        except Exception:
            return None

    def fetch_overview(self, start_date: date, end_date: date) -> OverviewResult:
        if self.iceberg_available():
            try:
                return self._fetch_overview_iceberg(start_date, end_date)
            except Exception:
                pass
        return self._fetch_overview_parquet(start_date, end_date)

    def _fetch_overview_iceberg(self, start_date: date, end_date: date) -> OverviewResult:
        import pandas as pd

        con = self._ensure_iceberg_con()
        pageviews_daily = con.execute(
            """
            SELECT date, pageviews
            FROM r2_iceberg.analytics.fct_pageviews_daily
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            [str(start_date), str(end_date)],
        ).df()
        errors_daily = con.execute(
            """
            SELECT date, errors
            FROM r2_iceberg.analytics.fct_errors_daily
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            [str(start_date), str(end_date)],
        ).df()
        if self._iceberg_table_exists("analytics", "fct_sessions_daily"):
            sessions_daily = con.execute(
                """
                SELECT date, sessions
                FROM r2_iceberg.analytics.fct_sessions_daily
                WHERE date BETWEEN ? AND ?
                ORDER BY date
                """,
                [str(start_date), str(end_date)],
            ).df()
        elif self._iceberg_table_exists("raw", "website_sessions"):
            sessions_daily = con.execute(
                """
                SELECT date, COUNT(DISTINCT session_id) AS sessions
                FROM r2_iceberg.raw.website_sessions
                WHERE date BETWEEN ? AND ?
                GROUP BY date
                ORDER BY date
                """,
                [str(start_date), str(end_date)],
            ).df()
        else:
            sessions_daily = con.execute(
                """
                SELECT date, COUNT(DISTINCT session_id) AS sessions
                FROM r2_iceberg.raw.website_events
                WHERE date BETWEEN ? AND ?
                GROUP BY date
                ORDER BY date
                """,
                [str(start_date), str(end_date)],
            ).df()

        pageviews_total = int(pageviews_daily["pageviews"].sum()) if not pageviews_daily.empty else 0
        errors_total = int(errors_daily["errors"].sum()) if not errors_daily.empty else 0
        events_total = con.execute(
            """
            SELECT COUNT(*)
            FROM r2_iceberg.raw.website_events
            WHERE date BETWEEN ? AND ?
            """,
            [str(start_date), str(end_date)],
        ).fetchone()[0]

        if self._iceberg_table_exists("raw", "website_sessions"):
            sessions_total = con.execute(
                """
                SELECT COUNT(DISTINCT session_id)
                FROM r2_iceberg.raw.website_sessions
                WHERE date BETWEEN ? AND ?
                """,
                [str(start_date), str(end_date)],
            ).fetchone()[0]
        else:
            sessions_total = con.execute(
                """
                SELECT COUNT(DISTINCT session_id)
                FROM r2_iceberg.raw.website_events
                WHERE date BETWEEN ? AND ?
                """,
                [str(start_date), str(end_date)],
            ).fetchone()[0]

        if pageviews_daily.empty:
            pageviews_daily = pd.DataFrame(columns=["date", "pageviews"])
        if sessions_daily.empty:
            sessions_daily = pd.DataFrame(columns=["date", "sessions"])

        return OverviewResult(
            source="iceberg",
            sessions=int(sessions_total) if sessions_total is not None else None,
            pageviews=pageviews_total,
            events=int(events_total) if events_total is not None else None,
            errors=errors_total,
            sessions_daily=sessions_daily,
            pageviews_daily=pageviews_daily,
        )

    def _fetch_overview_parquet(self, start_date: date, end_date: date) -> OverviewResult:
        import pandas as pd

        con = self._ensure_parquet_con()
        glob = self._events_glob()
        pageviews_daily = con.execute(
            """
            SELECT CAST(date AS DATE) AS date, COUNT(*) AS pageviews
            FROM read_parquet(?,
                hive_partitioning=true,
                union_by_name=true
            )
            WHERE event_name = 'page_view'
              AND CAST(date AS DATE) BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            [glob, str(start_date), str(end_date)],
        ).df()
        errors_daily = con.execute(
            """
            SELECT CAST(date AS DATE) AS date, COUNT(*) AS errors
            FROM read_parquet(?,
                hive_partitioning=true,
                union_by_name=true
            )
            WHERE event_name = 'error'
              AND CAST(date AS DATE) BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            [glob, str(start_date), str(end_date)],
        ).df()
        sessions_daily = con.execute(
            """
            SELECT CAST(date AS DATE) AS date, COUNT(DISTINCT session_id) AS sessions
            FROM read_parquet(?,
                hive_partitioning=true,
                union_by_name=true
            )
            WHERE CAST(date AS DATE) BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            [glob, str(start_date), str(end_date)],
        ).df()

        pageviews_total = int(pageviews_daily["pageviews"].sum()) if not pageviews_daily.empty else 0
        errors_total = int(errors_daily["errors"].sum()) if not errors_daily.empty else 0
        events_total = con.execute(
            """
            SELECT COUNT(*)
            FROM read_parquet(?,
                hive_partitioning=true,
                union_by_name=true
            )
            WHERE CAST(date AS DATE) BETWEEN ? AND ?
            """,
            [glob, str(start_date), str(end_date)],
        ).fetchone()[0]
        sessions_total = con.execute(
            """
            SELECT COUNT(DISTINCT session_id)
            FROM read_parquet(?,
                hive_partitioning=true,
                union_by_name=true
            )
            WHERE CAST(date AS DATE) BETWEEN ? AND ?
            """,
            [glob, str(start_date), str(end_date)],
        ).fetchone()[0]

        if pageviews_daily.empty:
            pageviews_daily = pd.DataFrame(columns=["date", "pageviews"])
        if sessions_daily.empty:
            sessions_daily = pd.DataFrame(columns=["date", "sessions"])

        return OverviewResult(
            source="parquet",
            sessions=int(sessions_total) if sessions_total is not None else None,
            pageviews=pageviews_total,
            events=int(events_total) if events_total is not None else None,
            errors=errors_total,
            sessions_daily=sessions_daily,
            pageviews_daily=pageviews_daily,
        )
