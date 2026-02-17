import os
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from app.layout.header import page_header
from lib.analytics.marts import load_latest_manifest, read_latest_parquet_df
from lib.ops.memory import log_mem
from lib.storage import paths as storage_paths
from lib.storage.s3_compat import (
    duckdb_httpfs_config,
    get_storage_config,
    is_configured,
    s3_url,
)
from shared.settings import get_settings
from shared.telemetry.config import get_config
from shared.telemetry import page_guard


with page_guard(os.path.basename(__file__)):
    page_header("Telemetry Admin", page_name=os.path.basename(__file__))
    settings = get_settings()
    if settings.safe_mode:
        st.warning("Safe mode is enabled. Telemetry queries are disabled.")
        st.stop()

    st.markdown("## Telemetry Overview")
    config = get_config()

    try:
        import duckdb
    except Exception as exc:
        st.error(f"DuckDB not available: {exc}")
        st.stop()

    con = duckdb.connect()

    sink_flag = config.sink.lower()
    storage_config = get_storage_config()
    use_storage = any(token in sink_flag for token in ("spaces", "r2", "s3")) and is_configured(
        storage_config
    )

    if use_storage:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        for key, value in duckdb_httpfs_config(storage_config).items():
            if value in ("", None):
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            con.execute(f"SET {key}='{value}'")

        events_glob = s3_url(storage_paths.telemetry_events_glob(), storage_config)
        sessions_glob = s3_url(storage_paths.telemetry_sessions_glob(), storage_config)
    else:
        log_dir = Path("data/logs")
        events_glob = str(log_dir / "events" / "date=*" / "events_*.jsonl.gz")
        sessions_glob = str(log_dir / "sessions" / "date=*" / "sessions_*.parquet")

    date_col, limit_col = st.columns([2, 1])
    with date_col:
        default_end = datetime.utcnow().date()
        default_start = default_end - timedelta(days=7)
        date_range = st.date_input(
            "Date range",
            value=(default_start, default_end),
            min_value=default_end - timedelta(days=365),
            max_value=default_end,
        )
    with limit_col:
        row_limit = st.number_input("Row limit", min_value=100, max_value=2000, value=500, step=100)

    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info("Select a start and end date to view telemetry.")
        st.stop()

    start_date, end_date = date_range
    if start_date > end_date:
        st.error("Start date must be before end date.")
        st.stop()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Sessions per day**")
        try:
            log_mem("telemetry_sessions:before")
            df_sessions = con.execute(
                """
                SELECT date, COUNT(*) AS sessions
                FROM read_parquet(? )
                WHERE date BETWEEN ? AND ?
                GROUP BY date
                ORDER BY date DESC
                """,
                [sessions_glob, str(start_date), str(end_date)],
            ).df()
            log_mem("telemetry_sessions:after")
            st.dataframe(df_sessions, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("No session snapshots yet.")

    with col2:
        st.markdown("**Page views per day**")
        try:
            log_mem("telemetry_page_views:before")
            df_views = con.execute(
                """
                SELECT CAST(ts_utc AS DATE) AS day, COUNT(*) AS page_views
                FROM read_json_auto(? )
                WHERE event_type = 'page_view'
                  AND CAST(ts_utc AS DATE) BETWEEN ? AND ?
                GROUP BY day
                ORDER BY day DESC
                """,
                [events_glob, str(start_date), str(end_date)],
            ).df()
            log_mem("telemetry_page_views:after")
            st.dataframe(df_views, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("No events yet.")

    with col3:
        st.markdown("**Errors per day**")
        try:
            log_mem("telemetry_errors:before")
            df_errors = con.execute(
                """
                SELECT CAST(ts_utc AS DATE) AS day, COUNT(*) AS errors
                FROM read_json_auto(? )
                WHERE event_type = 'error'
                  AND CAST(ts_utc AS DATE) BETWEEN ? AND ?
                GROUP BY day
                ORDER BY day DESC
                """,
                [events_glob, str(start_date), str(end_date)],
            ).df()
            log_mem("telemetry_errors:after")
            st.dataframe(df_errors, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("No errors logged.")

    st.markdown("---")
    st.markdown("### Recent events")
    try:
        log_mem("telemetry_recent:before")
        df_recent = con.execute(
            """
            SELECT ts_utc, page, event_type, duration_ms
            FROM read_json_auto(? )
            WHERE CAST(ts_utc AS DATE) BETWEEN ? AND ?
            ORDER BY ts_utc DESC
            LIMIT ?
            """,
            [events_glob, str(start_date), str(end_date), int(row_limit)],
        ).df()
        log_mem("telemetry_recent:after")
        st.dataframe(df_recent, use_container_width=True, hide_index=True)
    except Exception:
        st.caption("No events yet.")

    st.markdown("---")
    st.markdown("### Latest analytics mart")
    if not use_storage:
        st.caption("R2 storage is not configured; analytics marts are unavailable.")
    else:
        project_name = "databuilds"
        try:
            manifest = load_latest_manifest(project_name)
        except Exception as exc:
            st.caption(f"No analytics manifest found: {exc}")
        else:
            model_names = [entry.get("name") for entry in manifest.get("models", []) if entry.get("name")]
            if not model_names:
                st.caption("Analytics manifest is empty.")
            else:
                selected_model = st.selectbox("Mart model", model_names, key="analytics_mart_model")
                mart_limit = st.number_input(
                    "Row limit",
                    min_value=10,
                    max_value=1000,
                    value=200,
                    step=50,
                    key="analytics_mart_limit",
                )
                try:
                    df_mart = read_latest_parquet_df(
                        project_name,
                        selected_model,
                        limit=int(mart_limit),
                        manifest=manifest,
                    )
                    st.dataframe(df_mart, use_container_width=True, hide_index=True)
                except Exception as exc:
                    st.error(f"Unable to load analytics mart '{selected_model}': {exc}")
