from __future__ import annotations

import gzip
from typing import Iterable

from .s3_compat import get_bucket, get_client


def _normalize_key(key: str) -> str:
    return key.lstrip("/")


def put_bytes(
    key: str,
    data: bytes,
    content_type: str | None = None,
    content_encoding: str | None = None,
) -> None:
    client = get_client()
    bucket = get_bucket()
    params: dict[str, str] = {}
    if content_type:
        params["ContentType"] = content_type
    if content_encoding:
        params["ContentEncoding"] = content_encoding
    client.put_object(Bucket=bucket, Key=_normalize_key(key), Body=data, **params)


def get_bytes(key: str) -> bytes:
    client = get_client()
    bucket = get_bucket()
    response = client.get_object(Bucket=bucket, Key=_normalize_key(key))
    return response["Body"].read()


def put_file(
    key: str,
    path: str,
    content_type: str | None = None,
    content_encoding: str | None = None,
) -> None:
    client = get_client()
    bucket = get_bucket()
    extra: dict[str, str] = {}
    if content_type:
        extra["ContentType"] = content_type
    if content_encoding:
        extra["ContentEncoding"] = content_encoding
    if extra:
        client.upload_file(path, bucket, _normalize_key(key), ExtraArgs=extra)
    else:
        client.upload_file(path, bucket, _normalize_key(key))


def download_file(key: str, path: str) -> None:
    client = get_client()
    bucket = get_bucket()
    client.download_file(bucket, _normalize_key(key), path)


def list_keys(prefix: str) -> list[str]:
    client = get_client()
    bucket = get_bucket()
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=_normalize_key(prefix)):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def exists(key: str) -> bool:
    client = get_client()
    bucket = get_bucket()
    try:
        client.head_object(Bucket=bucket, Key=_normalize_key(key))
    except Exception:
        return False
    return True


def presign_get_url(key: str, expires_s: int = 3600) -> str:
    client = get_client()
    bucket = get_bucket()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": _normalize_key(key)},
        ExpiresIn=expires_s,
    )


def presign_put_url(
    key: str,
    expires_s: int = 900,
    content_type: str | None = None,
) -> str:
    client = get_client()
    bucket = get_bucket()
    params: dict[str, str] = {"Bucket": bucket, "Key": _normalize_key(key)}
    if content_type:
        params["ContentType"] = content_type
    return client.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_s)


def gzip_bytes(payload: bytes) -> bytes:
    return gzip.compress(payload)


def gunzip_bytes(payload: bytes) -> bytes:
    return gzip.decompress(payload)
