import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

from app import config as app_config
from app.layout.header import page_header
from lib.storage import paths as storage_paths
from lib.storage.s3_compat import (
    duckdb_httpfs_config,
    get_storage_config,
    is_configured,
    s3_url,
)
from shared.settings import get_settings
from shared.telemetry import page_guard
from shared.telemetry.config import get_config


def _is_mod_enabled() -> bool:
    entry = app_config.MOD_ACCESS.get("telemetry_admin") or app_config.MOD_ACCESS.get("telemetry")
    if entry is None:
        return False
    if isinstance(entry, dict):
        return bool(entry.get("enabled", True))
    return True


def _utc_today() -> datetime.date:
    return datetime.utcnow().date()


def _default_range(days: int) -> tuple[datetime.date, datetime.date]:
    end = _utc_today()
    start = end - timedelta(days=days - 1)
    return start, end


def _storage_paths(config) -> tuple[bool, str, str]:
    sink_flag = config.sink.lower()
    storage_config = get_storage_config()
    use_storage = any(token in sink_flag for token in ("spaces", "r2", "s3")) and is_configured(
        storage_config
    )

    if use_storage:
        events_glob = s3_url(storage_paths.telemetry_events_glob(), storage_config)
        sessions_glob = s3_url(storage_paths.telemetry_sessions_glob(), storage_config)
    else:
        log_dir = Path("data/logs")
        events_glob = str(log_dir / "events" / "date=*" / "events_*.jsonl.gz")
        sessions_glob = str(log_dir / "sessions" / "date=*" / "sessions_*.parquet")

    return use_storage, events_glob, sessions_glob


@st.cache_resource
def _duckdb_connection(httpfs_items: tuple[tuple[str, Any], ...]):
    import duckdb

    con = duckdb.connect()
    if httpfs_items:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        for key, value in dict(httpfs_items).items():
            if value in ("", None):
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            con.execute(f"SET {key}='{value}'")
    return con


@st.cache_data(ttl=300, max_entries=10)
def _query_df(
    query: str,
    params: tuple[Any, ...],
    use_storage: bool,
    storage_config,
):
    httpfs_items: tuple[tuple[str, Any], ...] = ()
    if use_storage:
        httpfs_items = tuple(sorted(duckdb_httpfs_config(storage_config).items()))
    con = _duckdb_connection(httpfs_items)
    return con.execute(query, params).df()


@st.cache_data(ttl=300, max_entries=10)
def _query_value(
    query: str,
    params: tuple[Any, ...],
    use_storage: bool,
    storage_config,
):
    httpfs_items: tuple[tuple[str, Any], ...] = ()
    if use_storage:
        httpfs_items = tuple(sorted(duckdb_httpfs_config(storage_config).items()))
    con = _duckdb_connection(httpfs_items)
    row = con.execute(query, params).fetchone()
    return row[0] if row else None


def _safe_date_range(date_range: Any) -> tuple[datetime.date, datetime.date] | None:
    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        return None
    start_date, end_date = date_range
    if start_date is None or end_date is None:
        return None
    if start_date > end_date:
        return None
    return start_date, end_date


def _fetch_latest_ts(events_glob: str, since: datetime.date, use_storage: bool, storage_config):
    try:
        latest = _query_value(
            """
            SELECT MAX(ts_utc)
            FROM read_json_auto(? )
            WHERE CAST(ts_utc AS DATE) >= ?
            """,
            (events_glob, str(since)),
            use_storage,
            storage_config,
        )
        return latest
    except Exception:
        return None


def _fetch_sessions_count(
    sessions_glob: str,
    events_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
) -> int | None:
    try:
        return _query_value(
            """
            SELECT COUNT(DISTINCT session_id)
            FROM read_parquet(? )
            WHERE date BETWEEN ? AND ?
            """,
            (sessions_glob, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        try:
            return _query_value(
                """
                SELECT COUNT(DISTINCT session_id)
                FROM read_json_auto(? )
                WHERE CAST(ts_utc AS DATE) BETWEEN ? AND ?
                """,
                (events_glob, str(start_date), str(end_date)),
                use_storage,
                storage_config,
            )
        except Exception:
            return None


def _fetch_event_count(
    events_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    where: str | None,
    use_storage: bool,
    storage_config,
) -> int | None:
    clause = "" if not where else f" AND {where}"
    try:
        return _query_value(
            f"""
            SELECT COUNT(*)
            FROM read_json_auto(? )
            WHERE CAST(ts_utc AS DATE) BETWEEN ? AND ?{clause}
            """,
            (events_glob, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        return None


def _fetch_sessions_daily(
    sessions_glob: str,
    events_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    try:
        return _query_df(
            """
            SELECT date, COUNT(DISTINCT session_id) AS sessions
            FROM read_parquet(? )
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (sessions_glob, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        return _query_df(
            """
            SELECT CAST(ts_utc AS DATE) AS date, COUNT(DISTINCT session_id) AS sessions
            FROM read_json_auto(? )
            WHERE CAST(ts_utc AS DATE) BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (events_glob, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )


def _fetch_pageviews_daily(
    events_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    return _query_df(
        """
        SELECT CAST(ts_utc AS DATE) AS date, COUNT(*) AS pageviews
        FROM read_json_auto(? )
        WHERE event_type = 'page_view'
          AND CAST(ts_utc AS DATE) BETWEEN ? AND ?
        GROUP BY date
        ORDER BY date
        """,
        (events_glob, str(start_date), str(end_date)),
        use_storage,
        storage_config,
    )


@st.cache_data(ttl=300, max_entries=10)
def _fetch_event_filters(
    events_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    try:
        df = _query_df(
            """
            SELECT DISTINCT event_type, page
            FROM read_json_auto(? )
            WHERE CAST(ts_utc AS DATE) BETWEEN ? AND ?
            """,
            (events_glob, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        return [], []

    event_names = sorted([value for value in df["event_type"].dropna().unique()])
    page_ids = sorted([value for value in df["page"].dropna().unique()])
    return event_names, page_ids


def _build_events_query(
    start_date: datetime.date,
    end_date: datetime.date,
    event_name: str | None,
    page_id: str | None,
    search_text: str | None,
):
    clauses = ["CAST(ts_utc AS DATE) BETWEEN ? AND ?"]
    params: list[Any] = [str(start_date), str(end_date)]
    if event_name:
        clauses.append("event_type = ?")
        params.append(event_name)
    if page_id:
        clauses.append("page = ?")
        params.append(page_id)
    if search_text:
        clauses.append("LOWER(CAST(payload AS VARCHAR)) LIKE ?")
        params.append(f"%{search_text.lower()}%")
    return " AND ".join(clauses), params


def _fetch_events_slice(
    events_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    event_name: str | None,
    page_id: str | None,
    search_text: str | None,
    limit: int,
    offset: int,
    use_storage: bool,
    storage_config,
):
    where_clause, params = _build_events_query(start_date, end_date, event_name, page_id, search_text)
    query = f"""
        SELECT ts_utc,
               event_type,
               page,
               session_id,
               duration_ms,
               json_extract_string(to_json(payload), '$.trace_id') AS trace_id,
               payload
        FROM read_json_auto(? )
        WHERE {where_clause}
        ORDER BY ts_utc DESC
        LIMIT ? OFFSET ?
    """
    full_params = (events_glob, *params, int(limit), int(offset))
    return _query_df(query, full_params, use_storage, storage_config)


def _fetch_session_snapshot(
    sessions_glob: str,
    session_id: str,
    use_storage: bool,
    storage_config,
):
    return _query_df(
        """
        SELECT ts_utc, date, event_count, error_count, pages_visited, last_page
        FROM read_parquet(? )
        WHERE session_id = ?
        ORDER BY ts_utc DESC
        LIMIT 1
        """,
        (sessions_glob, session_id),
        use_storage,
        storage_config,
    )


def _fetch_session_events(
    events_glob: str,
    session_id: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    return _query_df(
        """
        SELECT ts_utc, event_type, page, duration_ms, payload
        FROM read_json_auto(? )
        WHERE session_id = ?
          AND CAST(ts_utc AS DATE) BETWEEN ? AND ?
        ORDER BY ts_utc ASC
        LIMIT 500
        """,
        (events_glob, session_id, str(start_date), str(end_date)),
        use_storage,
        storage_config,
    )


def _fetch_trace_events(
    events_glob: str,
    trace_id: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    return _query_df(
        """
        SELECT ts_utc, event_type, page, session_id, payload
        FROM read_json_auto(? )
        WHERE CAST(ts_utc AS DATE) BETWEEN ? AND ?
          AND json_extract_string(to_json(payload), '$.trace_id') = ?
        ORDER BY ts_utc ASC
        LIMIT 200
        """,
        (events_glob, str(start_date), str(end_date), trace_id),
        use_storage,
        storage_config,
    )


with page_guard(os.path.basename(__file__)):
    page_header("Site Analytics", page_name=os.path.basename(__file__))
    settings = get_settings()
    if settings.safe_mode:
        st.warning("Safe mode is enabled. Telemetry queries are disabled.")
        st.stop()

    if not _is_mod_enabled():
        st.info("Not available")
        st.caption("This admin page is restricted. Contact the site owner if you need access.")
        st.stop()

    st.markdown("## Site Analytics & Telemetry")

    try:
        import duckdb  # noqa: F401
    except Exception as exc:
        st.error(f"DuckDB not available: {exc}")
        st.stop()

    config = get_config()
    storage_config = get_storage_config()
    use_storage, events_glob, sessions_glob = _storage_paths(config)

    lookback_start = _utc_today() - timedelta(days=30)
    latest_ts = _fetch_latest_ts(events_glob, lookback_start, use_storage, storage_config)
    if latest_ts:
        st.caption(f"Data freshness: {latest_ts} UTC")
    else:
        st.caption("Data freshness: unavailable")

    tab_overview, tab_events, tab_sessions = st.tabs(
        ["Overview", "Events Explorer", "Sessions / Traces"]
    )

    with tab_overview:
        st.markdown("### Overview")
        start_7d, end_7d = _default_range(7)
        start_30d, end_30d = _default_range(30)

        sessions_7d = _fetch_sessions_count(
            sessions_glob, events_glob, start_7d, end_7d, use_storage, storage_config
        )
        sessions_30d = _fetch_sessions_count(
            sessions_glob, events_glob, start_30d, end_30d, use_storage, storage_config
        )

        pageviews_7d = _fetch_event_count(
            events_glob, start_7d, end_7d, "event_type = 'page_view'", use_storage, storage_config
        )
        pageviews_30d = _fetch_event_count(
            events_glob, start_30d, end_30d, "event_type = 'page_view'", use_storage, storage_config
        )

        events_7d = _fetch_event_count(events_glob, start_7d, end_7d, None, use_storage, storage_config)
        events_30d = _fetch_event_count(
            events_glob, start_30d, end_30d, None, use_storage, storage_config
        )

        errors_7d = _fetch_event_count(
            events_glob, start_7d, end_7d, "event_type = 'error'", use_storage, storage_config
        )
        errors_30d = _fetch_event_count(
            events_glob, start_30d, end_30d, "event_type = 'error'", use_storage, storage_config
        )

        st.markdown("**Last 7 days**")
        cols = st.columns(5)
        cols[0].metric("Sessions", sessions_7d or 0)
        cols[1].metric("Pageviews", pageviews_7d or 0)
        cols[2].metric("Unique Visitors", sessions_7d or 0)
        cols[3].metric("Events", events_7d or 0)
        cols[4].metric("Errors", errors_7d or 0)

        st.markdown("**Last 30 days**")
        cols = st.columns(5)
        cols[0].metric("Sessions", sessions_30d or 0)
        cols[1].metric("Pageviews", pageviews_30d or 0)
        cols[2].metric("Unique Visitors", sessions_30d or 0)
        cols[3].metric("Events", events_30d or 0)
        cols[4].metric("Errors", errors_30d or 0)

        st.markdown("---")
        st.markdown("### Daily trends")
        try:
            sessions_daily = _fetch_sessions_daily(
                sessions_glob, events_glob, start_30d, end_30d, use_storage, storage_config
            )
            pageviews_daily = _fetch_pageviews_daily(
                events_glob, start_30d, end_30d, use_storage, storage_config
            )
            trend = sessions_daily.merge(pageviews_daily, on="date", how="outer")
            trend = trend.fillna(0).sort_values("date")
            if not trend.empty:
                trend["sessions"] = trend["sessions"].astype(int)
                trend["pageviews"] = trend["pageviews"].astype(int)
                st.line_chart(trend.set_index("date"))
            else:
                st.caption("No daily telemetry data available yet.")
        except Exception:
            st.caption("No daily telemetry data available yet.")

    with tab_events:
        st.markdown("### Events Explorer")
        date_col, limit_col = st.columns([2, 1])
        with date_col:
            default_start, default_end = _default_range(7)
            date_range = st.date_input(
                "Date range",
                value=(default_start, default_end),
                min_value=_utc_today() - timedelta(days=365),
                max_value=_utc_today(),
                key="events_date_range",
            )
        with limit_col:
            limit = st.number_input(
                "Rows per page",
                min_value=50,
                max_value=1000,
                value=250,
                step=50,
                key="events_limit",
            )

        safe_range = _safe_date_range(date_range)
        if not safe_range:
            st.info("Select a start and end date to explore events.")
        else:
            start_date, end_date = safe_range
            event_names, page_ids = _fetch_event_filters(
                events_glob, start_date, end_date, use_storage, storage_config
            )
            event_col, page_col, search_col = st.columns([1, 1, 2])
            with event_col:
                selected_event = st.selectbox(
                    "Event name",
                    options=["All"] + event_names,
                    index=0,
                    key="events_event_name",
                )
            with page_col:
                selected_page = st.selectbox(
                    "Page",
                    options=["All"] + page_ids,
                    index=0,
                    key="events_page_id",
                )
            with search_col:
                search_text = st.text_input("Search payload", key="events_search_text")

            filter_key = (
                start_date,
                end_date,
                selected_event,
                selected_page,
                search_text,
                int(limit),
            )
            if st.session_state.get("events_filter_key") != filter_key:
                st.session_state["events_filter_key"] = filter_key
                st.session_state["events_offset"] = 0

            offset = int(st.session_state.get("events_offset", 0))
            event_filter = None if selected_event == "All" else selected_event
            page_filter = None if selected_page == "All" else selected_page
            search_filter = search_text.strip() if search_text else None

            try:
                events_df = _fetch_events_slice(
                    events_glob,
                    start_date,
                    end_date,
                    event_filter,
                    page_filter,
                    search_filter,
                    int(limit),
                    offset,
                    use_storage,
                    storage_config,
                )
            except Exception as exc:
                st.error(f"Unable to load events: {exc}")
                events_df = None

            if events_df is not None:
                if events_df.empty:
                    st.caption("No events found for this filter.")
                else:
                    display_df = events_df[[
                        "ts_utc",
                        "event_type",
                        "page",
                        "session_id",
                        "duration_ms",
                        "trace_id",
                    ]].copy()
                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "ts_utc": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
                        },
                    )

                    export_df = events_df.copy()
                    try:
                        export_df["payload"] = export_df["payload"].apply(lambda value: str(value))
                    except Exception:
                        pass
                    st.download_button(
                        "Export CSV",
                        data=export_df.to_csv(index=False),
                        file_name="events_slice.csv",
                        mime="text/csv",
                    )

                    options = [
                        f"{row.ts_utc} | {row.event_type} | {row.page}"
                        for row in events_df.itertuples()
                    ]
                    selected = st.selectbox("Event details", options, key="events_detail_select")
                    selected_idx = options.index(selected)
                    payload = events_df.iloc[selected_idx]["payload"]
                    with st.expander("Event payload", expanded=False):
                        try:
                            st.json(payload)
                        except Exception:
                            st.code(str(payload))

                    col_prev, col_next, col_note = st.columns([1, 1, 2])
                    with col_prev:
                        if st.button("Previous", disabled=offset == 0):
                            st.session_state["events_offset"] = max(0, offset - int(limit))
                            st.rerun()
                    with col_next:
                        if st.button("Load more"):
                            st.session_state["events_offset"] = offset + int(limit)
                            st.rerun()
                    with col_note:
                        st.caption(f"Showing rows {offset + 1} to {offset + len(events_df)}")

    with tab_sessions:
        st.markdown("### Sessions / Traces")
        lookup_value = st.text_input("Session ID or trace ID", key="session_lookup")
        lookback_days = st.selectbox("Lookback window", options=[7, 30, 90], index=1)
        start_date = _utc_today() - timedelta(days=int(lookback_days))
        end_date = _utc_today()

        if lookup_value:
            session_snapshot = None
            try:
                session_snapshot = _fetch_session_snapshot(
                    sessions_glob, lookup_value, use_storage, storage_config
                )
            except Exception:
                session_snapshot = None

            session_events = None
            trace_events = None
            try:
                session_events = _fetch_session_events(
                    events_glob, lookup_value, start_date, end_date, use_storage, storage_config
                )
            except Exception:
                session_events = None

            try:
                trace_events = _fetch_trace_events(
                    events_glob, lookup_value, start_date, end_date, use_storage, storage_config
                )
            except Exception:
                trace_events = None

            if (session_events is None or session_events.empty) and (
                trace_events is None or trace_events.empty
            ):
                st.info("No matching session or trace found in the selected window.")
            else:
                if session_events is not None and not session_events.empty:
                    st.markdown("**Session metadata**")
                    first_seen = session_events["ts_utc"].iloc[0]
                    last_seen = session_events["ts_utc"].iloc[-1]
                    if session_snapshot is not None and not session_snapshot.empty:
                        snapshot = session_snapshot.iloc[0]
                        meta_cols = st.columns(4)
                        meta_cols[0].metric("First seen", str(first_seen))
                        meta_cols[1].metric("Last seen", str(last_seen))
                        meta_cols[2].metric("Events", int(snapshot["event_count"]))
                        meta_cols[3].metric("Errors", int(snapshot["error_count"]))
                        if snapshot.get("last_page"):
                            st.caption(f"Last page: {snapshot['last_page']}")
                        if snapshot.get("pages_visited"):
                            st.caption(f"Pages touched: {snapshot['pages_visited']}")
                    else:
                        meta_cols = st.columns(3)
                        meta_cols[0].metric("First seen", str(first_seen))
                        meta_cols[1].metric("Last seen", str(last_seen))
                        meta_cols[2].metric("Events", len(session_events))
                        st.caption(
                            f"Errors: {(session_events['event_type'] == 'error').sum()} · "
                            f"Pages touched: {len(session_events['page'].dropna().unique())}"
                        )

                    st.markdown("**Session timeline**")
                    st.dataframe(
                        session_events,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "ts_utc": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
                        },
                    )

                if trace_events is not None and not trace_events.empty:
                    st.markdown("**Trace details**")
                    st.dataframe(
                        trace_events,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "ts_utc": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
                        },
                    )
                    with st.expander("Trace payload", expanded=False):
                        try:
                            st.json(trace_events.iloc[0]["payload"])
                        except Exception:
                            st.code(str(trace_events.iloc[0]["payload"]))
