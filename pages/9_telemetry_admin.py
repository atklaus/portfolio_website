import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

from app import config as app_config
from app.layout.header import page_header
from lib.errors.boundary import get_app_env
from lib.errors.logging import log_exception
from lib.storage import paths as storage_paths
from lib.storage.s3_compat import (
    duckdb_httpfs_config,
    get_bucket,
    get_client,
    get_storage_config,
    is_configured,
    s3_url,
)
from shared.errors_ui import render_error_banner
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


def _date_range_list(start_date: datetime.date, end_date: datetime.date) -> list[datetime.date]:
    days: list[datetime.date] = []
    cursor = start_date
    while cursor <= end_date:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


@st.cache_data(ttl=300, max_entries=20)
def _prefix_has_objects(prefix: str, storage_config) -> bool:
    client = get_client(storage_config)
    bucket = get_bucket(storage_config)
    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    return bool(response.get("Contents"))


@st.cache_data(ttl=300, max_entries=10)
def _event_globs_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
) -> list[str]:
    days = _date_range_list(start_date, end_date)
    if use_storage:
        globs: list[str] = []
        for day in days:
            prefix = f"telemetry/events/date={day.isoformat()}/"
            if _prefix_has_objects(prefix, storage_config):
                globs.append(
                    s3_url(
                        f"{prefix}events_*.jsonl.gz",
                        storage_config,
                    )
                )
        return globs
    log_dir = Path("data/logs")
    globs: list[str] = []
    for day in days:
        path = log_dir / "events" / f"date={day.isoformat()}" / "events_*.jsonl.gz"
        if list(path.parent.glob(path.name)):
            globs.append(str(path))
    return globs


@st.cache_data(ttl=300, max_entries=10)
def _events_parquet_globs_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
) -> tuple[list[str], list[str]]:
    days = _date_range_list(start_date, end_date)
    missing: list[str] = []
    globs: list[str] = []
    if use_storage:
        for day in days:
            prefix = f"telemetry/events_parquet/date={day.isoformat()}/"
            if _prefix_has_objects(prefix, storage_config):
                globs.append(
                    s3_url(
                        f"{prefix}*.parquet",
                        storage_config,
                    )
                )
            else:
                missing.append(day.isoformat())
        return globs, missing

    log_dir = Path("data/logs") / "events_parquet"
    for day in days:
        path = log_dir / f"date={day.isoformat()}" / "*.parquet"
        if list(path.parent.glob(path.name)):
            globs.append(str(path))
        else:
            missing.append(day.isoformat())
    return globs, missing


def _events_source_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
) -> dict[str, Any]:
    parquet_globs, missing = _events_parquet_globs_for_range(
        start_date, end_date, use_storage, storage_config
    )
    if parquet_globs and not missing:
        union = _union_read_parquet(parquet_globs)
        return {
            "source": "parquet",
            "union": union,
            "missing": [],
            "columns": {
                "ts": "ts",
                "event": "event_name",
                "page": "page_id",
                "session": "session_id",
                "trace": "trace_id",
                "payload": "payload_json",
            },
        }

    json_globs = _event_globs_for_range(start_date, end_date, use_storage, storage_config)
    union = _union_read_json(json_globs)
    return {
        "source": "json",
        "union": union,
        "missing": missing,
        "columns": {
            "ts": "ts_utc",
            "event": "event_type",
            "page": "page",
            "session": "session_id",
            "trace": "trace_id",
            "payload": "payload",
        },
    }


@st.cache_data(ttl=300, max_entries=10)
def _session_globs_for_range(
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
) -> list[str]:
    days = _date_range_list(start_date, end_date)
    if use_storage:
        globs: list[str] = []
        for day in days:
            prefix = f"telemetry/sessions/date={day.isoformat()}/"
            if _prefix_has_objects(prefix, storage_config):
                globs.append(
                    s3_url(
                        f"{prefix}sessions_*.parquet",
                        storage_config,
                    )
                )
        return globs
    log_dir = Path("data/logs")
    globs: list[str] = []
    for day in days:
        path = log_dir / "sessions" / f"date={day.isoformat()}" / "sessions_*.parquet"
        if list(path.parent.glob(path.name)):
            globs.append(str(path))
    return globs


def _union_read_json(globs: list[str]) -> tuple[str, tuple[Any, ...]] | None:
    if not globs:
        return None
    parts = ["SELECT * FROM read_json_auto(? )"] * len(globs)
    return " UNION ALL ".join(parts), tuple(globs)


def _union_read_parquet(globs: list[str]) -> tuple[str, tuple[Any, ...]] | None:
    if not globs:
        return None
    parts = ["SELECT * FROM read_parquet(? )"] * len(globs)
    return " UNION ALL ".join(parts), tuple(globs)


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


@st.cache_data(ttl=300, max_entries=5)
def _list_prefix(prefix: str, storage_config):
    client = get_client(storage_config)
    bucket = get_bucket(storage_config)
    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=5)
    keys = [item.get("Key", "") for item in response.get("Contents", []) if item.get("Key")]
    return keys


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
                con.execute(f"SET {key}={value}")
            else:
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
    globs = _event_globs_for_range(since, _utc_today(), use_storage, storage_config)
    union = _union_read_json(globs)
    if not union:
        return None
    union_sql, union_params = union
    try:
        latest = _query_value(
            f"""
            SELECT MAX(ts_utc)
            FROM ({union_sql})
            WHERE CAST(ts_utc AS DATE) >= ?
            """,
            (*union_params, str(since)),
            use_storage,
            storage_config,
        )
        return latest
    except Exception:
        return None


@st.cache_data(ttl=300, max_entries=5)
def _latest_object_mtime(prefix: str, storage_config):
    client = get_client(storage_config)
    bucket = get_bucket(storage_config)
    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
    latest = None
    for item in response.get("Contents", []):
        ts = item.get("LastModified")
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def _fetch_sessions_count(
    sessions_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
) -> int | None:
    session_globs = _session_globs_for_range(start_date, end_date, use_storage, storage_config)
    union = _union_read_parquet(session_globs)
    try:
        if not union:
            raise RuntimeError("No session globs")
        union_sql, union_params = union
        return _query_value(
            f"""
            SELECT COUNT(DISTINCT session_id)
            FROM ({union_sql})
            WHERE date BETWEEN ? AND ?
            """,
            (*union_params, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        source = _events_source_for_range(start_date, end_date, use_storage, storage_config)
        union = source.get("union")
        if not union:
            return None
        union_sql, union_params = union
        ts_col = source["columns"]["ts"]
        session_col = source["columns"]["session"]
        try:
            return _query_value(
                f"""
                SELECT COUNT(DISTINCT {session_col})
                FROM ({union_sql})
                WHERE CAST({ts_col} AS DATE) BETWEEN ? AND ?
                """,
                (*union_params, str(start_date), str(end_date)),
                use_storage,
                storage_config,
            )
        except Exception:
            return None


def _fetch_event_count(
    source: dict[str, Any],
    start_date: datetime.date,
    end_date: datetime.date,
    where: str | None,
    use_storage: bool,
    storage_config,
) -> int | None:
    union = source.get("union")
    if not union:
        return None
    union_sql, union_params = union
    ts_col = source["columns"]["ts"]
    clause = "" if not where else f" AND {where}"
    try:
        return _query_value(
            f"""
            SELECT COUNT(*)
            FROM ({union_sql})
            WHERE CAST({ts_col} AS DATE) BETWEEN ? AND ?{clause}
            """,
            (*union_params, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        return None


def _fetch_sessions_daily(
    sessions_glob: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    session_globs = _session_globs_for_range(start_date, end_date, use_storage, storage_config)
    union = _union_read_parquet(session_globs)
    try:
        if not union:
            raise RuntimeError("No session globs")
        union_sql, union_params = union
        return _query_df(
            f"""
            SELECT date, COUNT(DISTINCT session_id) AS sessions
            FROM ({union_sql})
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (*union_params, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        source = _events_source_for_range(start_date, end_date, use_storage, storage_config)
        union = source.get("union")
        if not union:
            return _query_df("SELECT NULL WHERE FALSE", tuple(), use_storage, storage_config)
        union_sql, union_params = union
        ts_col = source["columns"]["ts"]
        session_col = source["columns"]["session"]
        return _query_df(
            f"""
            SELECT CAST({ts_col} AS DATE) AS date, COUNT(DISTINCT {session_col}) AS sessions
            FROM ({union_sql})
            WHERE CAST({ts_col} AS DATE) BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (*union_params, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )


def _fetch_pageviews_daily(
    source: dict[str, Any],
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    union = source.get("union")
    if not union:
        return _query_df("SELECT NULL WHERE FALSE", tuple(), use_storage, storage_config)
    union_sql, union_params = union
    ts_col = source["columns"]["ts"]
    event_col = source["columns"]["event"]
    return _query_df(
        f"""
        SELECT CAST({ts_col} AS DATE) AS date, COUNT(*) AS pageviews
        FROM ({union_sql})
        WHERE {event_col} = 'page_view'
          AND CAST({ts_col} AS DATE) BETWEEN ? AND ?
        GROUP BY date
        ORDER BY date
        """,
        (*union_params, str(start_date), str(end_date)),
        use_storage,
        storage_config,
    )


@st.cache_data(ttl=300, max_entries=10)
def _fetch_event_filters(
    source: dict[str, Any],
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    try:
        union = source.get("union")
        if not union:
            return [], []
        union_sql, union_params = union
        ts_col = source["columns"]["ts"]
        event_col = source["columns"]["event"]
        page_col = source["columns"]["page"]
        df = _query_df(
            f"""
            SELECT DISTINCT {event_col} AS event_name, {page_col} AS page_id
            FROM ({union_sql})
            WHERE CAST({ts_col} AS DATE) BETWEEN ? AND ?
            """,
            (*union_params, str(start_date), str(end_date)),
            use_storage,
            storage_config,
        )
    except Exception:
        return [], []

    event_names = sorted([value for value in df["event_name"].dropna().unique()])
    page_ids = sorted([value for value in df["page_id"].dropna().unique()])
    return event_names, page_ids


def _build_events_query(
    start_date: datetime.date,
    end_date: datetime.date,
    event_name: str | None,
    page_id: str | None,
    search_text: str | None,
    columns: dict[str, str],
    source_name: str,
):
    ts_col = columns["ts"]
    event_col = columns["event"]
    page_col = columns["page"]
    payload_col = columns["payload"]

    clauses = [f"CAST({ts_col} AS DATE) BETWEEN ? AND ?"]
    params: list[Any] = [str(start_date), str(end_date)]
    if event_name:
        clauses.append(f"{event_col} = ?")
        params.append(event_name)
    if page_id:
        clauses.append(f"{page_col} = ?")
        params.append(page_id)
    if search_text:
        if source_name == "parquet":
            clauses.append(f"LOWER({payload_col}) LIKE ?")
        else:
            clauses.append(f"LOWER(CAST({payload_col} AS VARCHAR)) LIKE ?")
        params.append(f"%{search_text.lower()}%")
    return " AND ".join(clauses), params


def _fetch_events_slice(
    source: dict[str, Any],
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
    union = source.get("union")
    if not union:
        return _query_df("SELECT NULL WHERE FALSE", tuple(), use_storage, storage_config)
    union_sql, union_params = union
    columns = source["columns"]
    where_clause, params = _build_events_query(
        start_date,
        end_date,
        event_name,
        page_id,
        search_text,
        columns,
        source["source"],
    )
    ts_col = columns["ts"]
    event_col = columns["event"]
    page_col = columns["page"]
    session_col = columns["session"]
    payload_col = columns["payload"]
    trace_col = columns["trace"]
    if source["source"] == "parquet":
        query = f"""
            SELECT {ts_col} AS ts_utc,
                   {event_col} AS event_type,
                   {page_col} AS page,
                   {session_col} AS session_id,
                   NULL AS duration_ms,
                   {trace_col} AS trace_id,
                   {payload_col} AS payload
            FROM ({union_sql})
            WHERE {where_clause}
            ORDER BY {ts_col} DESC
            LIMIT ? OFFSET ?
        """
    else:
        query = f"""
            SELECT {ts_col} AS ts_utc,
                   {event_col} AS event_type,
                   {page_col} AS page,
                   {session_col} AS session_id,
                   duration_ms,
                   json_extract_string(to_json(payload), '$.trace_id') AS trace_id,
                   {payload_col} AS payload
            FROM ({union_sql})
            WHERE {where_clause}
            ORDER BY {ts_col} DESC
            LIMIT ? OFFSET ?
        """
    full_params = (*union_params, *params, int(limit), int(offset))
    return _query_df(query, full_params, use_storage, storage_config)


def _fetch_session_snapshot(
    sessions_glob: str,
    session_id: str,
    use_storage: bool,
    storage_config,
):
    today = _utc_today()
    start_date = today - timedelta(days=90)
    session_globs = _session_globs_for_range(start_date, today, use_storage, storage_config)
    union = _union_read_parquet(session_globs)
    if not union:
        return _query_df("SELECT NULL WHERE FALSE", tuple(), use_storage, storage_config)
    union_sql, union_params = union
    return _query_df(
        f"""
        SELECT ts_utc, date, event_count, error_count, pages_visited, last_page
        FROM ({union_sql})
        WHERE session_id = ?
        ORDER BY ts_utc DESC
        LIMIT 1
        """,
        (*union_params, session_id),
        use_storage,
        storage_config,
    )


def _fetch_session_events(
    source: dict[str, Any],
    session_id: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    union = source.get("union")
    if not union:
        return _query_df("SELECT NULL WHERE FALSE", tuple(), use_storage, storage_config)
    union_sql, union_params = union
    columns = source["columns"]
    ts_col = columns["ts"]
    event_col = columns["event"]
    page_col = columns["page"]
    session_col = columns["session"]
    payload_col = columns["payload"]
    if source["source"] == "parquet":
        query = f"""
            SELECT {ts_col} AS ts_utc,
                   {event_col} AS event_type,
                   {page_col} AS page,
                   NULL AS duration_ms,
                   {payload_col} AS payload
            FROM ({union_sql})
            WHERE {session_col} = ?
              AND CAST({ts_col} AS DATE) BETWEEN ? AND ?
            ORDER BY {ts_col} ASC
            LIMIT 500
        """
    else:
        query = f"""
            SELECT {ts_col} AS ts_utc,
                   {event_col} AS event_type,
                   {page_col} AS page,
                   duration_ms,
                   {payload_col} AS payload
            FROM ({union_sql})
            WHERE {session_col} = ?
              AND CAST({ts_col} AS DATE) BETWEEN ? AND ?
            ORDER BY {ts_col} ASC
            LIMIT 500
        """
    return _query_df(
        query,
        (*union_params, session_id, str(start_date), str(end_date)),
        use_storage,
        storage_config,
    )


def _fetch_trace_events(
    source: dict[str, Any],
    trace_id: str,
    start_date: datetime.date,
    end_date: datetime.date,
    use_storage: bool,
    storage_config,
):
    union = source.get("union")
    if not union:
        return _query_df("SELECT NULL WHERE FALSE", tuple(), use_storage, storage_config)
    union_sql, union_params = union
    columns = source["columns"]
    ts_col = columns["ts"]
    event_col = columns["event"]
    page_col = columns["page"]
    session_col = columns["session"]
    payload_col = columns["payload"]
    trace_col = columns["trace"]
    if source["source"] == "parquet":
        query = f"""
            SELECT {ts_col} AS ts_utc,
                   {event_col} AS event_type,
                   {page_col} AS page,
                   {session_col} AS session_id,
                   {payload_col} AS payload
            FROM ({union_sql})
            WHERE CAST({ts_col} AS DATE) BETWEEN ? AND ?
              AND {trace_col} = ?
            ORDER BY {ts_col} ASC
            LIMIT 200
        """
    else:
        query = f"""
            SELECT {ts_col} AS ts_utc,
                   {event_col} AS event_type,
                   {page_col} AS page,
                   {session_col} AS session_id,
                   {payload_col} AS payload
            FROM ({union_sql})
            WHERE CAST({ts_col} AS DATE) BETWEEN ? AND ?
              AND json_extract_string(to_json(payload), '$.trace_id') = ?
            ORDER BY {ts_col} ASC
            LIMIT 200
        """
    return _query_df(
        query,
        (*union_params, str(start_date), str(end_date), trace_id),
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

    if use_storage and st.button("Check data freshness"):
        try:
            latest_ts = _latest_object_mtime("telemetry/events/", storage_config)
        except Exception:
            latest_ts = None
        if latest_ts:
            st.caption(f"Data freshness: {latest_ts} UTC")
        else:
            st.caption("Data freshness: unavailable")
    else:
        st.caption("Data freshness: click to check")

    with st.expander("Storage diagnostics", expanded=False):
        if not use_storage:
            st.caption("Storage is not configured; using local log paths.")
        else:
            endpoint = storage_config.endpoint_url
            st.caption(f"Bucket: {storage_config.bucket}")
            st.caption(f"Endpoint: {endpoint}")
            st.caption(f"DuckDB endpoint: {duckdb_httpfs_config(storage_config).get('s3_endpoint')}")
            st.caption(f"DuckDB use_ssl: {duckdb_httpfs_config(storage_config).get('s3_use_ssl')}")
            if st.button("Reset DuckDB connection"):
                st.cache_resource.clear()
                st.cache_data.clear()
                st.success("DuckDB cache cleared. Retry your query.")
            if st.button("Test R2 access"):
                try:
                    events_keys = _list_prefix("telemetry/events/", storage_config)
                    ops_keys = _list_prefix("ops/logs/", storage_config)
                    st.write({"telemetry/events": events_keys, "ops/logs": ops_keys})
                except Exception as exc:
                    st.error(f"R2 list failed: {exc}")

    tab_overview, tab_events, tab_sessions = st.tabs(
        ["Overview", "Events Explorer", "Sessions / Traces"]
    )

    with tab_overview:
        st.markdown("### Overview")
        if st.button("Load overview metrics"):
            st.session_state["overview_loaded"] = True
        loaded = st.session_state.get("overview_loaded")
        if not loaded:
            st.info("Click 'Load overview metrics' to run queries.")
        else:
            start_7d, end_7d = _default_range(7)
            start_30d, end_30d = _default_range(30)

            source_7d = _events_source_for_range(start_7d, end_7d, use_storage, storage_config)
            source_30d = _events_source_for_range(start_30d, end_30d, use_storage, storage_config)
            if source_30d["source"] == "json" and (end_30d - start_30d).days > 7:
                st.warning("Parquet is missing for some dates. Limiting overview to 7 days.")
                start_30d, end_30d = _default_range(7)
                source_30d = _events_source_for_range(
                    start_30d, end_30d, use_storage, storage_config
                )
            if source_7d["source"] == "json" and source_7d["missing"]:
                st.info(
                    "Some dates aren't rolled up to Parquet yet, falling back to raw logs (slower)."
                )
            st.caption(
                f"Data source: {'Parquet (fast)' if source_7d['source'] == 'parquet' else 'JSONL (slow)'}"
            )

            sessions_7d = _fetch_sessions_count(
                sessions_glob, start_7d, end_7d, use_storage, storage_config
            )
            sessions_30d = _fetch_sessions_count(
                sessions_glob, start_30d, end_30d, use_storage, storage_config
            )

            pageviews_where_7d = f"{source_7d['columns']['event']} = 'page_view'"
            pageviews_where_30d = f"{source_30d['columns']['event']} = 'page_view'"
            errors_where_7d = f"{source_7d['columns']['event']} = 'error'"
            errors_where_30d = f"{source_30d['columns']['event']} = 'error'"

            pageviews_7d = _fetch_event_count(
                source_7d, start_7d, end_7d, pageviews_where_7d,
                use_storage,
                storage_config,
            )
            pageviews_30d = _fetch_event_count(
                source_30d, start_30d, end_30d, pageviews_where_30d,
                use_storage,
                storage_config,
            )

            events_7d = _fetch_event_count(source_7d, start_7d, end_7d, None, use_storage, storage_config)
            events_30d = _fetch_event_count(
                source_30d, start_30d, end_30d, None, use_storage, storage_config
            )

            errors_7d = _fetch_event_count(
                source_7d, start_7d, end_7d, errors_where_7d,
                use_storage,
                storage_config,
            )
            errors_30d = _fetch_event_count(
                source_30d, start_30d, end_30d, errors_where_30d,
                use_storage,
                storage_config,
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
                    sessions_glob, start_30d, end_30d, use_storage, storage_config
                )
                pageviews_daily = _fetch_pageviews_daily(
                    source_30d, start_30d, end_30d, use_storage, storage_config
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
        if st.button("Run events query"):
            st.session_state["events_run"] = True
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
        if not st.session_state.get("events_run"):
            st.info("Click 'Run events query' to load results.")
        elif safe_range and (safe_range[1] - safe_range[0]).days > 31:
            st.warning("Date range too large. Please limit to 31 days for performance.")
        elif not safe_range:
            st.info("Select a start and end date to explore events.")
        else:
            start_date, end_date = safe_range
            source = _events_source_for_range(start_date, end_date, use_storage, storage_config)
            st.caption(f"Data source: {'Parquet (fast)' if source['source'] == 'parquet' else 'JSONL (slow)'}")
            query_allowed = True
            if source["source"] == "json" and source["missing"]:
                st.warning(
                    "Some dates aren't rolled up to Parquet yet, falling back to raw logs (slower)."
                )
            if source["source"] == "json" and (end_date - start_date).days > 7:
                st.info("Reduce the range to 7 days or less for JSONL queries.")
                query_allowed = False

            if not query_allowed:
                event_names, page_ids = [], []
            else:
                event_names, page_ids = _fetch_event_filters(
                    source, start_date, end_date, use_storage, storage_config
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

            events_df = None
            if query_allowed:
                try:
                    events_df = _fetch_events_slice(
                        source,
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
                    _handle_query_error(exc, "telemetry_admin_events")
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
                            if isinstance(payload, str):
                                st.json(json.loads(payload))
                            else:
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
            source = _events_source_for_range(start_date, end_date, use_storage, storage_config)
            if source["source"] == "json" and source["missing"]:
                st.warning(
                    "Some dates aren't rolled up to Parquet yet, falling back to raw logs (slower)."
                )
            if source["source"] == "json" and (end_date - start_date).days > 7:
                st.info("Reducing lookback to 7 days for JSONL queries.")
                start_date = end_date - timedelta(days=6)
                source = _events_source_for_range(start_date, end_date, use_storage, storage_config)

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
                    source, lookup_value, start_date, end_date, use_storage, storage_config
                )
            except Exception:
                session_events = None

            try:
                trace_events = _fetch_trace_events(
                    source, lookup_value, start_date, end_date, use_storage, storage_config
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
