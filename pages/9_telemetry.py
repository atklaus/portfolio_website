import json
import os
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

import streamlit as st

from app import config as app_config
from app.layout.header import page_header
from lib.errors.boundary import get_app_env
from lib.errors.logging import log_exception
from shared.duckdb_client import ensure_r2_iceberg_attached, get_conn, query_df
from shared.errors_ui import render_error_banner
from shared.settings import get_settings
from shared.telemetry import page_guard


def _is_mod_enabled() -> bool:
    entry = app_config.MOD_ACCESS.get("telemetry_admin") or app_config.MOD_ACCESS.get("telemetry")
    if entry is None:
        return False
    if isinstance(entry, dict):
        return bool(entry.get("enabled", True))
    return True


def _utc_today() -> date:
    return datetime.utcnow().date()


def _default_range(days: int) -> tuple[date, date]:
    end = _utc_today()
    start = end - timedelta(days=days - 1)
    return start, end


def _safe_date_range(raw_range: Any) -> tuple[date, date] | None:
    if not isinstance(raw_range, (tuple, list)) or len(raw_range) != 2:
        return None
    start_date, end_date = raw_range
    if start_date is None or end_date is None:
        return None
    if start_date > end_date:
        return None
    return start_date, end_date


def _handle_query_error(exc: Exception, page_id: str) -> None:
    trace_id = uuid4().hex[:10]
    try:
        log_exception(exc, trace_id, page_id, extra={"component": "telemetry_admin"})
    except Exception:
        pass
    render_error_banner(trace_id)
    if get_app_env() != "prod":
        with st.expander("Query error details"):
            st.exception(exc)


def _sql_df_safe(sql: str, params: dict[str, Any] | None = None):
    try:
        return query_df(sql, params), None
    except Exception as exc:
        return None, exc


def _sql_status_panel() -> None:
    st.markdown("### SQL Status")

    checks: list[tuple[str, str]] = [
        (
            "DuckDB attached databases",
            "select * from duckdb_databases() order by database_name",
        ),
        (
            "stg_website_events rows + max timestamp",
            """
            select count(*) as n, max(ts) as max_ts
            from r2_iceberg.analytics.stg_website_events
            """,
        ),
        (
            "stg_website_sessions rows + max timestamp",
            """
            select count(*) as n, max(ts_utc) as max_ts
            from r2_iceberg.analytics.stg_website_sessions
            """,
        ),
        (
            "fct_sessions_daily rows + max day",
            """
            select count(*) as n, max(date) as max_day
            from r2_iceberg.analytics.fct_sessions_daily
            """,
        ),
        (
            "fct_pageviews_daily rows + max day",
            """
            select count(*) as n, max(date) as max_day
            from r2_iceberg.analytics.fct_pageviews_daily
            """,
        ),
        (
            "fct_errors_daily rows + max day",
            """
            select count(*) as n, max(date) as max_day
            from r2_iceberg.analytics.fct_errors_daily
            """,
        ),
    ]

    for title, sql in checks:
        st.caption(title)
        df, err = _sql_df_safe(sql)
        if err is not None:
            st.error(str(err))
            continue
        st.dataframe(df, use_container_width=True, hide_index=True)


def _value_or_none(df, column: str):
    if df is None or df.empty or column not in df.columns:
        return None
    value = df.iloc[0][column]
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    return value


def _sessions_pipeline_debug_panel() -> None:
    st.markdown("### Sessions Pipeline Debug")

    table_presence_sql = """
    select
      table_catalog,
      table_schema,
      table_name
    from information_schema.tables
    where table_name in ('website_events', 'website_sessions', 'stg_website_events', 'stg_website_sessions')
      and table_schema in ('raw', 'r2_iceberg.raw', 'analytics', 'r2_iceberg.analytics')
    order by table_catalog, table_schema, table_name
    """

    st.caption("Raw table presence")
    raw_presence_df, raw_presence_err = _sql_df_safe(table_presence_sql)
    if raw_presence_err is not None:
        st.error(str(raw_presence_err))
        raw_presence_df = None
    else:
        st.dataframe(raw_presence_df, use_container_width=True, hide_index=True)

    def _table_ref(table_catalog: str, table_schema: str, table_name: str) -> str:
        # Handle dbt-local quoted schemas (e.g., "r2_iceberg.raw") and attached catalogs.
        if "." in table_schema:
            return f'"{table_schema}".{table_name}'
        if table_catalog and table_catalog not in {"warehouse", "main", "temp", "system"}:
            return f"{table_catalog}.{table_schema}.{table_name}"
        return f"{table_schema}.{table_name}"

    raw_events_ref = None
    raw_sessions_ref = None
    if raw_presence_df is not None and not raw_presence_df.empty:
        raw_rows = raw_presence_df[
            (raw_presence_df["table_name"].isin(["website_events", "website_sessions"]))
            & (raw_presence_df["table_schema"].isin(["raw", "r2_iceberg.raw"]))
        ]
        for row in raw_rows.itertuples(index=False):
            ref = _table_ref(str(row.table_catalog), str(row.table_schema), str(row.table_name))
            if row.table_name == "website_events":
                raw_events_ref = ref
            elif row.table_name == "website_sessions":
                raw_sessions_ref = ref

    raw_events_exists = raw_events_ref is not None
    raw_sessions_exists = raw_sessions_ref is not None

    st.caption("Raw counts")
    raw_counts_df = None
    if raw_events_exists and raw_events_ref:
        raw_counts_sql = f"""
        select
          (select count(*) from {raw_events_ref}) as n_events_raw,
          {'(select count(*) from ' + raw_sessions_ref + ')' if raw_sessions_exists and raw_sessions_ref else 'cast(null as bigint)'} as n_sessions_raw
        """
        raw_counts_df, raw_counts_err = _sql_df_safe(raw_counts_sql)
        if raw_counts_err is not None:
            st.error(str(raw_counts_err))
            raw_counts_df = None
        else:
            st.dataframe(raw_counts_df, use_container_width=True, hide_index=True)
    else:
        raw_counts_df, _ = _sql_df_safe("select cast(null as bigint) as n_events_raw, cast(null as bigint) as n_sessions_raw")
        st.dataframe(raw_counts_df, use_container_width=True, hide_index=True)

    st.caption("Staging counts")
    stg_counts_df, stg_counts_err = _sql_df_safe(
        """
        select
          (select count(*) from r2_iceberg.analytics.stg_website_events) as n_events_stg,
          (select count(*) from r2_iceberg.analytics.stg_website_sessions) as n_sessions_stg
        """
    )
    if stg_counts_err is not None:
        st.error(str(stg_counts_err))
        stg_counts_df = None
    else:
        st.dataframe(stg_counts_df, use_container_width=True, hide_index=True)

    st.caption("Freshness windows")
    freshness_df = None
    if raw_events_exists and raw_events_ref:
        freshness_sql = f"""
        select
          (select min(ts) from {raw_events_ref}) as raw_events_min_ts,
          (select max(ts) from {raw_events_ref}) as raw_events_max_ts,
          (select min(ts_utc) from r2_iceberg.analytics.stg_website_sessions) as stg_sessions_min_ts,
          (select max(ts_utc) from r2_iceberg.analytics.stg_website_sessions) as stg_sessions_max_ts
        """
        freshness_df, freshness_err = _sql_df_safe(freshness_sql)
        if freshness_err is not None:
            st.error(str(freshness_err))
            freshness_df = None
        else:
            st.dataframe(freshness_df, use_container_width=True, hide_index=True)
    else:
        freshness_df, _ = _sql_df_safe(
            """
            select
              cast(null as timestamp) as raw_events_min_ts,
              cast(null as timestamp) as raw_events_max_ts,
              (select min(ts_utc) from r2_iceberg.analytics.stg_website_sessions) as stg_sessions_min_ts,
              (select max(ts_utc) from r2_iceberg.analytics.stg_website_sessions) as stg_sessions_max_ts
            """
        )
        st.dataframe(freshness_df, use_container_width=True, hide_index=True)

    raw_tables = set()
    if raw_presence_df is not None and not raw_presence_df.empty and "table_name" in raw_presence_df.columns:
        raw_tables = set(
            raw_presence_df[
                raw_presence_df["table_schema"].isin(["raw", "r2_iceberg.raw"])
            ]["table_name"].tolist()
        )

    n_events_raw = _value_or_none(raw_counts_df, "n_events_raw")
    n_sessions_raw = _value_or_none(raw_counts_df, "n_sessions_raw")
    n_sessions_stg = _value_or_none(stg_counts_df, "n_sessions_stg")

    st.markdown("**Interpretation**")
    notes: list[str] = []

    if "website_sessions" not in raw_tables:
        notes.append(
            "`r2_iceberg.raw.website_sessions` is missing. Ingestion is not creating the raw sessions table, or sessions are intentionally derived from events only."
        )
    if n_events_raw is not None and int(n_events_raw) > 0 and (n_sessions_raw is not None and int(n_sessions_raw) == 0):
        notes.append(
            "Events exist but raw sessions are zero. Sessions are not being emitted by the app, or ingestion is ignoring session objects."
        )
    if n_sessions_raw is not None and int(n_sessions_raw) > 0 and (n_sessions_stg is not None and int(n_sessions_stg) == 0):
        notes.append(
            "Raw sessions exist but staging sessions are zero. The dbt session model logic is filtering or dropping rows."
        )

    if not notes:
        notes.append("No obvious session gap detected by these checks.")

    for note in notes:
        st.write(f"- {note}")


OVERVIEW_TOTALS_SQL = """
select
  coalesce((
    select sum(sessions)
    from r2_iceberg.analytics.fct_sessions_daily
    where date between cast(:start_date as date) and cast(:end_date as date)
  ), 0)::bigint as sessions,
  coalesce((
    select count(distinct coalesce(nullif(session_id, ''), instance_id))
    from r2_iceberg.analytics.stg_website_events
    where date between cast(:start_date as date) and cast(:end_date as date)
  ), 0)::bigint as users,
  coalesce((
    select sum(pageviews)
    from r2_iceberg.analytics.fct_pageviews_daily
    where date between cast(:start_date as date) and cast(:end_date as date)
  ), 0)::bigint as pageviews,
  coalesce((
    select sum(errors)
    from r2_iceberg.analytics.fct_errors_daily
    where date between cast(:start_date as date) and cast(:end_date as date)
  ), 0)::bigint as error_count,
  coalesce((
    select count(*)
    from r2_iceberg.analytics.stg_website_events
    where date between cast(:start_date as date) and cast(:end_date as date)
  ), 0)::bigint as event_count
"""


OVERVIEW_DAILY_SQL = """
with days as (
  select day
  from generate_series(cast(:start_date as date), cast(:end_date as date), interval 1 day) as t(day)
),
sessions_daily as (
  select date as day, sessions
  from r2_iceberg.analytics.fct_sessions_daily
  where date between cast(:start_date as date) and cast(:end_date as date)
),
pageviews_daily as (
  select date as day, pageviews
  from r2_iceberg.analytics.fct_pageviews_daily
  where date between cast(:start_date as date) and cast(:end_date as date)
),
errors_daily as (
  select date as day, errors as error_count
  from r2_iceberg.analytics.fct_errors_daily
  where date between cast(:start_date as date) and cast(:end_date as date)
),
users_daily as (
  select
    date as day,
    count(distinct coalesce(nullif(session_id, ''), instance_id)) as users
  from r2_iceberg.analytics.stg_website_events
  where date between cast(:start_date as date) and cast(:end_date as date)
  group by 1
)
select
  d.day,
  coalesce(s.sessions, 0)::bigint as sessions,
  coalesce(u.users, 0)::bigint as users,
  coalesce(p.pageviews, 0)::bigint as pageviews,
  coalesce(e.error_count, 0)::bigint as error_count
from days d
left join sessions_daily s on d.day = s.day
left join users_daily u on d.day = u.day
left join pageviews_daily p on d.day = p.day
left join errors_daily e on d.day = e.day
order by d.day
"""


EVENT_NAMES_SQL = """
select distinct event_name
from r2_iceberg.analytics.stg_website_events
where date between cast(:start_date as date) and cast(:end_date as date)
  and event_name is not null
order by event_name
"""


EVENT_PAGES_SQL = """
select distinct page_id
from r2_iceberg.analytics.stg_website_events
where date between cast(:start_date as date) and cast(:end_date as date)
  and page_id is not null
order by page_id
"""


EVENTS_EXPLORER_SQL = """
select
  ts as event_ts,
  date as day,
  event_name,
  page_id,
  session_id,
  trace_id,
  app_version,
  level,
  message,
  payload_json
from r2_iceberg.analytics.stg_website_events
where date between cast(:start_date as date) and cast(:end_date as date)
  and (:event_name is null or event_name = :event_name)
  and (:page_id is null or page_id = :page_id)
  and (:session_id_like is null or lower(session_id) like lower(:session_id_like))
  and (
    :payload_like is null
    or lower(coalesce(payload_json, '')) like lower(:payload_like)
  )
order by ts desc
limit :limit_rows
offset :offset_rows
"""


SESSIONS_PAGE_OPTIONS_SQL = """
select distinct last_page
from r2_iceberg.analytics.stg_website_sessions
where date between cast(:start_date as date) and cast(:end_date as date)
  and last_page is not null
order by last_page
"""


SESSIONS_EXPLORER_SQL = """
select
  ts_utc as session_start_ts,
  date as day,
  session_id,
  pages_visited,
  event_count,
  error_count,
  total_runtime_ms,
  app_version,
  last_page
from r2_iceberg.analytics.stg_website_sessions
where date between cast(:start_date as date) and cast(:end_date as date)
  and (:session_id_like is null or lower(session_id) like lower(:session_id_like))
  and (:last_page is null or last_page = :last_page)
order by ts_utc desc
limit :limit_rows
"""


SESSION_EVENTS_SQL = """
select
  ts as event_ts,
  event_name,
  page_id,
  trace_id,
  payload_json
from r2_iceberg.analytics.stg_website_events
where date between cast(:start_date as date) and cast(:end_date as date)
  and session_id = :session_id
order by ts asc
limit 500
"""


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
        ensure_r2_iceberg_attached(get_conn())
    except Exception as exc:
        st.error("DuckDB/Iceberg attach failed. Telemetry SQL queries are skipped.")
        st.caption("Set `R2_ICEBERG_*` and R2 credentials, then retry.")
        if get_app_env() != "prod":
            st.exception(exc)
        if st.button("Reset DuckDB connection cache"):
            st.cache_resource.clear()
            st.cache_data.clear()
            st.success("Cache cleared. Retry when env vars are available.")
        st.stop()

    if st.button("Reset DuckDB connection cache"):
        st.cache_resource.clear()
        st.cache_data.clear()
        st.success("Cache cleared.")

    with st.expander("Data Source Status", expanded=False):
        _sql_status_panel()

    with st.expander("Sessions Pipeline Debug", expanded=False):
        _sessions_pipeline_debug_panel()

    tab_overview, tab_events, tab_sessions = st.tabs(["Overview", "Events Explorer", "Sessions Explorer"])

    with tab_overview:
        st.markdown("### Overview")

        start_7d, end_7d = _default_range(7)
        start_30d, end_30d = _default_range(30)

        totals_7d, totals_7d_err = _sql_df_safe(
            OVERVIEW_TOTALS_SQL,
            {"start_date": start_7d.isoformat(), "end_date": end_7d.isoformat()},
        )
        totals_30d, totals_30d_err = _sql_df_safe(
            OVERVIEW_TOTALS_SQL,
            {"start_date": start_30d.isoformat(), "end_date": end_30d.isoformat()},
        )

        if totals_7d_err or totals_30d_err:
            _handle_query_error(totals_7d_err or totals_30d_err, "telemetry_admin_overview")
        else:
            row_7d = totals_7d.iloc[0]
            row_30d = totals_30d.iloc[0]

            st.markdown("**Last 7 days**")
            cols = st.columns(5)
            cols[0].metric("Sessions", int(row_7d["sessions"]))
            cols[1].metric("Users", int(row_7d["users"]))
            cols[2].metric("Pageviews", int(row_7d["pageviews"]))
            cols[3].metric("Events", int(row_7d["event_count"]))
            cols[4].metric("Errors", int(row_7d["error_count"]))

            st.markdown("**Last 30 days**")
            cols = st.columns(5)
            cols[0].metric("Sessions", int(row_30d["sessions"]))
            cols[1].metric("Users", int(row_30d["users"]))
            cols[2].metric("Pageviews", int(row_30d["pageviews"]))
            cols[3].metric("Events", int(row_30d["event_count"]))
            cols[4].metric("Errors", int(row_30d["error_count"]))

        trend_range = st.date_input(
            "Daily trend range",
            value=_default_range(30),
            min_value=_utc_today() - timedelta(days=365),
            max_value=_utc_today(),
            key="overview_trend_range",
        )
        safe_range = _safe_date_range(trend_range)
        if safe_range is None:
            st.info("Select a valid start/end date for trends.")
        else:
            trend_start, trend_end = safe_range
            trend_df, trend_err = _sql_df_safe(
                OVERVIEW_DAILY_SQL,
                {"start_date": trend_start.isoformat(), "end_date": trend_end.isoformat()},
            )
            if trend_err is not None:
                _handle_query_error(trend_err, "telemetry_admin_daily_trends")
            elif trend_df is None or trend_df.empty:
                st.caption("No daily telemetry data available yet.")
            else:
                st.line_chart(
                    trend_df,
                    x="day",
                    y=["sessions", "users", "pageviews", "error_count"],
                    use_container_width=True,
                )
                st.dataframe(trend_df, use_container_width=True, hide_index=True)

    with tab_events:
        st.markdown("### Events Explorer")

        date_range = st.date_input(
            "Date range",
            value=_default_range(7),
            min_value=_utc_today() - timedelta(days=365),
            max_value=_utc_today(),
            key="events_range",
        )

        safe_range = _safe_date_range(date_range)
        if safe_range is None:
            st.info("Select a valid start and end date.")
        else:
            start_date, end_date = safe_range
            event_names_df, event_names_err = _sql_df_safe(
                EVENT_NAMES_SQL,
                {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )
            page_ids_df, page_ids_err = _sql_df_safe(
                EVENT_PAGES_SQL,
                {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )

            if event_names_err is not None or page_ids_err is not None:
                _handle_query_error(
                    event_names_err or page_ids_err,
                    "telemetry_admin_event_filters",
                )
            else:
                event_options = ["All"]
                page_options = ["All"]
                if event_names_df is not None and not event_names_df.empty:
                    event_options.extend(event_names_df["event_name"].tolist())
                if page_ids_df is not None and not page_ids_df.empty:
                    page_options.extend(page_ids_df["page_id"].tolist())

                filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([1, 1, 1, 2])
                with filter_col1:
                    selected_event = st.selectbox("Event", options=event_options, index=0)
                with filter_col2:
                    selected_page = st.selectbox("Page", options=page_options, index=0)
                with filter_col3:
                    limit_rows = int(
                        st.number_input(
                            "Rows",
                            min_value=50,
                            max_value=1000,
                            value=250,
                            step=50,
                            key="events_limit_rows",
                        )
                    )
                with filter_col4:
                    search_payload = st.text_input("Payload contains", key="events_search_payload")

                session_search = st.text_input("Session ID contains", key="events_session_search")
                filter_key = (
                    start_date.isoformat(),
                    end_date.isoformat(),
                    selected_event,
                    selected_page,
                    search_payload,
                    session_search,
                    limit_rows,
                )
                if st.session_state.get("events_filter_key") != filter_key:
                    st.session_state["events_filter_key"] = filter_key
                    st.session_state["events_offset_rows"] = 0
                offset_rows = int(st.session_state.get("events_offset_rows", 0))

                params = {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "event_name": None if selected_event == "All" else selected_event,
                    "page_id": None if selected_page == "All" else selected_page,
                    "session_id_like": None if not session_search.strip() else f"%{session_search.strip()}%",
                    "payload_like": None if not search_payload.strip() else f"%{search_payload.strip()}%",
                    "limit_rows": limit_rows,
                    "offset_rows": offset_rows,
                }

                events_df, events_err = _sql_df_safe(EVENTS_EXPLORER_SQL, params)
                if events_err is not None:
                    _handle_query_error(events_err, "telemetry_admin_events")
                elif events_df is None or events_df.empty:
                    st.caption("No events found for this filter.")
                else:
                    st.dataframe(
                        events_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "event_ts": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss")
                        },
                    )

                    st.download_button(
                        "Export CSV",
                        data=events_df.to_csv(index=False),
                        file_name="events_explorer.csv",
                        mime="text/csv",
                    )

                    details = [
                        f"{row.event_ts} | {row.event_name} | {row.page_id}"
                        for row in events_df.itertuples()
                    ]
                    selected_detail = st.selectbox("Event payload", details, key="event_payload_select")
                    selected_idx = details.index(selected_detail)
                    payload = events_df.iloc[selected_idx].get("payload_json")
                    with st.expander("Payload JSON", expanded=False):
                        if payload is None:
                            st.caption("No payload available.")
                        else:
                            try:
                                st.json(json.loads(payload))
                            except Exception:
                                st.code(str(payload))

                    prev_col, next_col, note_col = st.columns([1, 1, 2])
                    with prev_col:
                        if st.button("Previous", disabled=offset_rows == 0, key="events_prev"):
                            st.session_state["events_offset_rows"] = max(0, offset_rows - limit_rows)
                            st.rerun()
                    with next_col:
                        if st.button("Load more", key="events_next"):
                            st.session_state["events_offset_rows"] = offset_rows + limit_rows
                            st.rerun()
                    with note_col:
                        st.caption(f"Showing rows {offset_rows + 1} to {offset_rows + len(events_df)}")

    with tab_sessions:
        st.markdown("### Sessions Explorer")

        session_range = st.date_input(
            "Date range",
            value=_default_range(30),
            min_value=_utc_today() - timedelta(days=365),
            max_value=_utc_today(),
            key="sessions_range",
        )

        safe_range = _safe_date_range(session_range)
        if safe_range is None:
            st.info("Select a valid start and end date.")
        else:
            start_date, end_date = safe_range

            page_options_df, page_options_err = _sql_df_safe(
                SESSIONS_PAGE_OPTIONS_SQL,
                {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )
            if page_options_err is not None:
                _handle_query_error(page_options_err, "telemetry_admin_sessions_options")
            else:
                page_options = ["All"]
                if page_options_df is not None and not page_options_df.empty:
                    page_options.extend(page_options_df["last_page"].tolist())

                filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])
                with filter_col1:
                    session_search = st.text_input(
                        "Session ID contains", key="sessions_session_search"
                    )
                with filter_col2:
                    selected_last_page = st.selectbox(
                        "Last page",
                        options=page_options,
                        index=0,
                        key="sessions_last_page",
                    )
                with filter_col3:
                    limit_rows = int(
                        st.number_input(
                            "Rows",
                            min_value=50,
                            max_value=1000,
                            value=250,
                            step=50,
                            key="sessions_limit_rows",
                        )
                    )

                sessions_df, sessions_err = _sql_df_safe(
                    SESSIONS_EXPLORER_SQL,
                    {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "session_id_like": None
                        if not session_search.strip()
                        else f"%{session_search.strip()}%",
                        "last_page": None if selected_last_page == "All" else selected_last_page,
                        "limit_rows": limit_rows,
                    },
                )

                if sessions_err is not None:
                    _handle_query_error(sessions_err, "telemetry_admin_sessions")
                elif sessions_df is None or sessions_df.empty:
                    st.caption("No sessions found for this filter.")
                else:
                    st.dataframe(
                        sessions_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "session_start_ts": st.column_config.DatetimeColumn(
                                format="YYYY-MM-DD HH:mm:ss"
                            )
                        },
                    )

                    choices = [
                        f"{row.session_start_ts} | {row.session_id}"
                        for row in sessions_df.itertuples()
                    ]
                    selected_session = st.selectbox(
                        "Session event timeline",
                        choices,
                        key="session_timeline_select",
                    )
                    session_idx = choices.index(selected_session)
                    session_id = sessions_df.iloc[session_idx]["session_id"]

                    timeline_df, timeline_err = _sql_df_safe(
                        SESSION_EVENTS_SQL,
                        {
                            "start_date": start_date.isoformat(),
                            "end_date": end_date.isoformat(),
                            "session_id": session_id,
                        },
                    )
                    if timeline_err is not None:
                        _handle_query_error(timeline_err, "telemetry_admin_session_events")
                    elif timeline_df is None or timeline_df.empty:
                        st.caption("No events found for the selected session in this window.")
                    else:
                        st.markdown("**Session events**")
                        st.dataframe(
                            timeline_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "event_ts": st.column_config.DatetimeColumn(
                                    format="YYYY-MM-DD HH:mm:ss"
                                )
                            },
                        )
