from __future__ import annotations

import json
from typing import Any

import duckdb

from lib.storage import get_bytes
from lib.storage.s3_compat import duckdb_httpfs_config, get_storage_config, is_configured, s3_url


def load_latest_manifest(project: str) -> dict[str, Any]:
    key = f"analytics/{project}/manifest/latest.json"
    payload = get_bytes(key)
    return json.loads(payload.decode("utf-8"))


def _latest_key_for_model(manifest: dict[str, Any], model: str) -> str:
    for entry in manifest.get("models", []):
        if entry.get("name") == model and entry.get("latest_key"):
            return entry["latest_key"]
    raise KeyError(f"Model '{model}' not found in manifest.")


def read_latest_parquet_df(
    project: str,
    model: str,
    limit: int | None = 200,
    manifest: dict[str, Any] | None = None,
):
    if not is_configured(get_storage_config()):
        raise RuntimeError("Storage is not configured.")

    manifest = manifest or load_latest_manifest(project)
    key = _latest_key_for_model(manifest, model)

    storage_config = get_storage_config()
    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    for setting_key, value in duckdb_httpfs_config(storage_config).items():
        if value in ("", None):
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        con.execute(f"SET {setting_key}='{value}'")

    parquet_url = s3_url(key, storage_config)
    if limit is None:
        return con.execute("SELECT * FROM read_parquet(? )", [parquet_url]).df()
    return con.execute("SELECT * FROM read_parquet(? ) LIMIT ?", [parquet_url, int(limit)]).df()
