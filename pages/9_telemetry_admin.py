import os
from pathlib import Path

import streamlit as st

from app.layout.header import page_header
from shared.telemetry.config import get_config
from shared.telemetry import page_guard


with page_guard(os.path.basename(__file__)):
    page_header("Telemetry Admin", page_name=os.path.basename(__file__))

    st.markdown("## Telemetry Overview")
    config = get_config()

    try:
        import duckdb
    except Exception as exc:
        st.error(f"DuckDB not available: {exc}")
        st.stop()

    con = duckdb.connect()

    use_spaces = "spaces" in config.sink.lower() and config.spaces_bucket

    if use_spaces:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        con.execute(f"SET s3_region='{config.spaces_region}'")
        con.execute(f"SET s3_endpoint='{config.spaces_endpoint}'")
        con.execute(f"SET s3_access_key_id='{config.spaces_access_key_id}'")
        con.execute(f"SET s3_secret_access_key='{config.spaces_secret_access_key}'")
        con.execute("SET s3_url_style='path'")
        con.execute("SET s3_use_ssl=true")

        base_prefix = config.spaces_prefix.rstrip("/")
        events_glob = f"s3://{config.spaces_bucket}/{base_prefix}/events/date=*/events_*.jsonl.gz"
        sessions_glob = f"s3://{config.spaces_bucket}/{base_prefix}/sessions/date=*/sessions_*.parquet"
    else:
        log_dir = Path("data/logs")
        events_glob = str(log_dir / "events" / "date=*" / "events_*.jsonl.gz")
        sessions_glob = str(log_dir / "sessions" / "date=*" / "sessions_*.parquet")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Sessions per day**")
        try:
            df_sessions = con.execute(
                """
                SELECT date, COUNT(*) AS sessions
                FROM read_parquet(? )
                GROUP BY date
                ORDER BY date DESC
                """,
                [sessions_glob],
            ).df()
            st.dataframe(df_sessions, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("No session snapshots yet.")

    with col2:
        st.markdown("**Page views per day**")
        try:
            df_views = con.execute(
                """
                SELECT CAST(ts_utc AS DATE) AS day, COUNT(*) AS page_views
                FROM read_json_auto(? )
                WHERE event_type = 'page_view'
                GROUP BY day
                ORDER BY day DESC
                """,
                [events_glob],
            ).df()
            st.dataframe(df_views, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("No events yet.")

    with col3:
        st.markdown("**Errors per day**")
        try:
            df_errors = con.execute(
                """
                SELECT CAST(ts_utc AS DATE) AS day, COUNT(*) AS errors
                FROM read_json_auto(? )
                WHERE event_type = 'error'
                GROUP BY day
                ORDER BY day DESC
                """,
                [events_glob],
            ).df()
            st.dataframe(df_errors, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("No errors logged.")

    st.markdown("---")
    st.markdown("### Recent events")
    try:
        df_recent = con.execute(
            """
            SELECT ts_utc, page, event_type, duration_ms
            FROM read_json_auto(? )
            ORDER BY ts_utc DESC
            LIMIT 50
            """,
            [events_glob],
        ).df()
        st.dataframe(df_recent, use_container_width=True, hide_index=True)
    except Exception:
        st.caption("No events yet.")
