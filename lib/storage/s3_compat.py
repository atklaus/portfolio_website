from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
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


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _provider_config(prefix: str, region_default: str = "") -> dict[str, str]:
    return {
        "bucket": _get_secret(f"{prefix}_BUCKET"),
        "region": _first_nonempty(_get_secret(f"{prefix}_REGION"), region_default),
        "endpoint_url": _get_secret(f"{prefix}_ENDPOINT"),
        "access_key_id": _get_secret(f"{prefix}_ACCESS_KEY_ID"),
        "secret_access_key": _get_secret(f"{prefix}_SECRET_ACCESS_KEY"),
    }


@dataclass(frozen=True)
class StorageConfig:
    provider: str
    bucket: str
    region: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str

    def is_configured(self) -> bool:
        if not (self.bucket and self.access_key_id and self.secret_access_key):
            return False
        if self.provider in {"r2", "spaces"} and not self.endpoint_url:
            return False
        return True


@lru_cache(maxsize=1)
def _load_config() -> StorageConfig:
    r2 = _provider_config("R2", region_default="auto")
    if r2["bucket"]:
        return StorageConfig(
            provider="r2",
            bucket=r2["bucket"],
            region=r2["region"] or "auto",
            endpoint_url=r2["endpoint_url"],
            access_key_id=r2["access_key_id"],
            secret_access_key=r2["secret_access_key"],
        )
    spaces = _provider_config("SPACES")
    if spaces["bucket"]:
        return StorageConfig(
            provider="spaces",
            bucket=spaces["bucket"],
            region=spaces["region"],
            endpoint_url=spaces["endpoint_url"],
            access_key_id=spaces["access_key_id"],
            secret_access_key=spaces["secret_access_key"],
        )
    s3 = _provider_config("S3")
    return StorageConfig(
        provider="s3" if s3["bucket"] else "",
        bucket=s3["bucket"],
        region=s3["region"],
        endpoint_url=s3["endpoint_url"],
        access_key_id=s3["access_key_id"],
        secret_access_key=s3["secret_access_key"],
    )


def get_storage_config(reload: bool = False) -> StorageConfig:
    if reload:
        _load_config.cache_clear()
        _cached_client.cache_clear()
    return _load_config()


def is_configured(config: StorageConfig | None = None) -> bool:
    return (config or get_storage_config()).is_configured()


def get_bucket(config: StorageConfig | None = None) -> str:
    cfg = config or get_storage_config()
    if not cfg.bucket:
        raise RuntimeError("Storage bucket is not configured.")
    return cfg.bucket


def endpoint_url(config: StorageConfig | None = None) -> str:
    return _normalize_endpoint_url((config or get_storage_config()).endpoint_url)


def _normalize_endpoint_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://{value}"


def _normalize_endpoint_host(value: str) -> str:
    if not value:
        return ""
    if value.startswith("http://"):
        value = value[len("http://") :]
    elif value.startswith("https://"):
        value = value[len("https://") :]
    value = value.lstrip("/")
    return value.rstrip("/")


def _build_client(cfg: StorageConfig):
    if not cfg.is_configured():
        raise RuntimeError("Storage credentials are not configured.")
    import boto3
    import botocore.config

    endpoint = _normalize_endpoint_url(cfg.endpoint_url)
    return boto3.client(
        "s3",
        region_name=cfg.region or None,
        endpoint_url=endpoint or None,
        aws_access_key_id=cfg.access_key_id or None,
        aws_secret_access_key=cfg.secret_access_key or None,
        config=botocore.config.Config(s3={"addressing_style": "path"}),
    )


@lru_cache(maxsize=1)
def _cached_client():
    return _build_client(get_storage_config())


def get_client(config: StorageConfig | None = None):
    if config is None:
        return _cached_client()
    return _build_client(config)


def s3_url(key: str, config: StorageConfig | None = None) -> str:
    cfg = config or get_storage_config()
    bucket = cfg.bucket
    if not bucket:
        raise RuntimeError("Storage bucket is not configured.")
    norm_key = key.lstrip("/")
    return f"s3://{bucket}/{norm_key}"


def duckdb_httpfs_config(config: StorageConfig | None = None) -> dict[str, Any]:
    cfg = config or get_storage_config()
    if not cfg.is_configured():
        return {}
    raw_endpoint = cfg.endpoint_url
    endpoint_host = _normalize_endpoint_host(raw_endpoint)
    use_ssl = True
    if raw_endpoint:
        use_ssl = not raw_endpoint.startswith("http://")
    return {
        "s3_region": cfg.region,
        "s3_endpoint": endpoint_host,
        "s3_access_key_id": cfg.access_key_id,
        "s3_secret_access_key": cfg.secret_access_key,
        "s3_url_style": "path",
        "s3_use_ssl": use_ssl,
    }
