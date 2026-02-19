from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

_NAMED_PARAM_PATTERN = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _get_secret(key: str) -> str:
    value = os.environ.get(key)
    if value:
        return value
    try:
        if key in st.secrets:
            secret_val = st.secrets.get(key, "")
            return str(secret_val) if secret_val is not None else ""
    except Exception:
        pass
    return ""


def _require_secret(key: str) -> str:
    value = _get_secret(key)
    if not value:
        raise RuntimeError(f"Missing required secret: {key}")
    return value


def _sql_escape(value: Any) -> str:
    return str(value).replace("'", "''")


def _duckdb_path() -> str:
    path = os.environ.get("DBT_DUCKDB_PATH", "analytics/artifacts/warehouse.duckdb")
    return str(Path(path).expanduser())


@st.cache_resource
def get_conn():
    import duckdb

    path = _duckdb_path()
    con = duckdb.connect(path)
    con.execute("PRAGMA threads=4")
    con.execute("SET preserve_insertion_order=false")
    return con


def ensure_r2_iceberg_attached(conn) -> None:
    marker = conn.execute(
        """
        SELECT 1
        FROM duckdb_tables()
        WHERE table_name = 'r2_iceberg_attach_marker'
          AND temporary
        LIMIT 1
        """
    ).fetchone()
    if marker:
        return

    existing = conn.execute(
        """
        SELECT 1
        FROM duckdb_databases()
        WHERE database_name = 'r2_iceberg'
        LIMIT 1
        """
    ).fetchone()
    if existing:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS r2_iceberg_attach_marker(dummy INTEGER)")
        return

    account_id = _require_secret("R2_ACCOUNT_ID")
    access_key = _require_secret("R2_ACCESS_KEY_ID")
    secret_key = _require_secret("R2_SECRET_ACCESS_KEY")
    catalog_uri = _require_secret("R2_ICEBERG_CATALOG_URI").strip()
    warehouse = _require_secret("R2_ICEBERG_WAREHOUSE").strip()
    token = _require_secret("R2_ICEBERG_TOKEN").strip()

    endpoint = _get_secret("R2_ENDPOINT").strip() or f"{account_id}.r2.cloudflarestorage.com"
    endpoint = endpoint.replace("https://", "").replace("http://", "").strip("/")
    if catalog_uri and not catalog_uri.startswith(("http://", "https://")):
        catalog_uri = "https://" + catalog_uri.lstrip("/")

    for ext in ("httpfs", "iceberg"):
        try:
            conn.execute(f"INSTALL {ext}")
        except Exception:
            pass
        conn.execute(f"LOAD {ext}")

    conn.execute("SET s3_url_style='path'")
    conn.execute("SET s3_region='auto'")
    conn.execute("SET s3_use_ssl=true")
    conn.execute("SET s3_endpoint=?", [endpoint])

    conn.execute("DROP SECRET IF EXISTS r2_s3")
    conn.execute("DROP SECRET IF EXISTS r2_catalog")

    conn.execute(
        f"""
        CREATE SECRET r2_s3 (
            TYPE s3,
            KEY_ID '{_sql_escape(access_key)}',
            SECRET '{_sql_escape(secret_key)}',
            REGION 'auto',
            ENDPOINT '{_sql_escape(endpoint)}',
            URL_STYLE 'path'
        )
        """
    )
    conn.execute(
        f"""
        CREATE SECRET r2_catalog (
            TYPE iceberg,
            TOKEN '{_sql_escape(token)}'
        )
        """
    )
    conn.execute(
        f"""
        ATTACH '{_sql_escape(warehouse)}' AS r2_iceberg
        (TYPE iceberg, ENDPOINT '{_sql_escape(catalog_uri)}', SECRET r2_catalog)
        """
    )
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS r2_iceberg_attach_marker(dummy INTEGER)")


def _bind_named_params(sql: str, params: dict[str, Any]) -> tuple[str, list[Any]]:
    ordered_values: list[Any] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in params:
            raise KeyError(f"Missing SQL parameter: {key}")
        ordered_values.append(params[key])
        return "?"

    bound_sql = _NAMED_PARAM_PATTERN.sub(_replace, sql)
    return bound_sql, ordered_values


def _rewrite_local_schema_refs(sql: str) -> str:
    rewritten = sql
    rewritten = rewritten.replace("r2_iceberg.analytics.", '"r2_iceberg.analytics".')
    rewritten = rewritten.replace("r2_iceberg.raw.", '"r2_iceberg.raw".')
    return rewritten


def _should_retry_with_local_schema(exc: Exception) -> bool:
    msg = str(exc)
    if 'Catalog "r2_iceberg" does not exist' in msg:
        return True
    if "Did you mean \"r2_iceberg.analytics." in msg:
        return True
    if "Did you mean \"r2_iceberg.raw." in msg:
        return True
    return False


def query_df(sql: str, params: dict[str, Any] | list[Any] | tuple[Any, ...] | None = None) -> pd.DataFrame:
    conn = get_conn()
    ensure_r2_iceberg_attached(conn)

    def _run(statement: str) -> pd.DataFrame:
        if params is None:
            return conn.execute(statement).df()
        if isinstance(params, dict):
            bound_sql, ordered = _bind_named_params(statement, params)
            return conn.execute(bound_sql, ordered).df()
        return conn.execute(statement, params).df()

    try:
        return _run(sql)
    except Exception as exc:
        if not _should_retry_with_local_schema(exc):
            raise
        rewritten = _rewrite_local_schema_refs(sql)
        if rewritten == sql:
            raise
        return _run(rewritten)


def query_scalar(sql: str, params: dict[str, Any] | list[Any] | tuple[Any, ...] | None = None) -> Any:
    df = query_df(sql, params)
    if df.empty:
        return None
    return df.iloc[0, 0]
