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

    # Optional override for S3 endpoint (useful for local/dev). If not provided,
    # default to the Cloudflare R2 account endpoint.
    r2_endpoint = _get_secret("R2_ENDPOINT")
    if r2_endpoint:
        r2_endpoint = r2_endpoint.strip()
    else:
        r2_endpoint = f"{account_id}.r2.cloudflarestorage.com"

    # DuckDB expects the endpoint without scheme.
    r2_endpoint = r2_endpoint.replace("https://", "").replace("http://", "")
    r2_endpoint = r2_endpoint.lstrip("/").rstrip("/")

    catalog_uri = _require_secret("R2_ICEBERG_CATALOG_URI")
    warehouse = _require_secret("R2_ICEBERG_WAREHOUSE")
    token = _require_secret("R2_ICEBERG_TOKEN")

    # Ensure Iceberg REST catalog URI includes scheme
    catalog_uri = catalog_uri.strip()
    if catalog_uri and not catalog_uri.startswith(("http://", "https://")):
        catalog_uri = "https://" + catalog_uri.lstrip("/")

    con = duckdb.connect()
    print(f"duckdb_version={duckdb.__version__}")
    # Extensions must be loaded before using Iceberg secret providers.
    for ext in ("httpfs", "iceberg"):
        try:
            con.execute(f"INSTALL {ext}")
        except Exception:
            pass
        con.execute(f"LOAD {ext}")
    con.execute("SET s3_url_style='path'")

    # Make sure DuckDB httpfs uses the same endpoint and path-style URLs for R2
    con.execute("SET s3_endpoint=?", [r2_endpoint])
    con.execute("SET s3_region='auto'")
    con.execute("SET s3_use_ssl=true")

    # Make reruns idempotent
    con.execute("DROP SECRET IF EXISTS r2_s3")
    con.execute("DROP SECRET IF EXISTS r2_catalog")
    con.execute("DETACH DATABASE IF EXISTS r2_iceberg")
    con.execute(
        f"""
        CREATE SECRET r2_s3 (
            TYPE s3,
            KEY_ID '{_sql_escape(access_key)}',
            SECRET '{_sql_escape(secret_key)}',
            REGION 'auto',
            ENDPOINT '{_sql_escape(r2_endpoint)}',
            URL_STYLE 'path'
        )
        """
    )
    con.execute(
        f"""
        CREATE SECRET r2_catalog (
            TYPE iceberg,
            TOKEN '{_sql_escape(token)}'
        )
        """
    )
    con.execute(
        f"""
        ATTACH '{_sql_escape(warehouse)}' AS r2_iceberg
        (TYPE iceberg, ENDPOINT '{_sql_escape(catalog_uri)}', SECRET r2_catalog)
        """
    )
    return con
