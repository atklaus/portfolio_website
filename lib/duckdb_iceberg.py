from __future__ import annotations

import os
from typing import Any


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


def _require_secret(key: str) -> str:
    value = _get_secret(key)
    if not value:
        raise RuntimeError(f"Missing required secret: {key}")
    return value


def _sql_escape(value: Any) -> str:
    return str(value).replace("'", "''")


def connect_iceberg():
    import duckdb

    account_id = _require_secret("R2_ACCOUNT_ID")
    access_key = _require_secret("R2_ACCESS_KEY_ID")
    secret_key = _require_secret("R2_SECRET_ACCESS_KEY")
    catalog_uri = _require_secret("R2_ICEBERG_CATALOG_URI")
    warehouse = _require_secret("R2_ICEBERG_WAREHOUSE")
    token = _require_secret("R2_ICEBERG_TOKEN")

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("INSTALL iceberg")
    con.execute("LOAD iceberg")
    con.execute("SET s3_url_style='path'")

    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    con.execute(
        f"""
        CREATE SECRET r2_s3 (
            TYPE S3,
            KEY_ID '{_sql_escape(access_key)}',
            SECRET '{_sql_escape(secret_key)}',
            REGION 'auto',
            ENDPOINT '{_sql_escape(endpoint)}',
            URL_STYLE 'path'
        )
        """
    )
    con.execute(
        f"""
        CREATE SECRET r2_catalog (
            TYPE ICEBERG,
            TOKEN '{_sql_escape(token)}'
        )
        """
    )
    con.execute(
        f"""
        ATTACH '{_sql_escape(warehouse)}' AS r2_iceberg
        (TYPE ICEBERG, ENDPOINT '{_sql_escape(catalog_uri)}', SECRET 'r2_catalog')
        """
    )
    return con
