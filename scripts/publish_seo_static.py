from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
import botocore.config

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"

SEO_FILES: tuple[tuple[str, Path, str], ...] = (
    ("sitemap.xml", STATIC_DIR / "sitemap.xml", "application/xml; charset=utf-8"),
    ("robots.txt", STATIC_DIR / "robots.txt", "text/plain; charset=utf-8"),
)


def _get_env(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value:
        return value
    return default


def _require_env(key: str) -> str:
    value = _get_env(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def _normalize_endpoint(value: str) -> str:
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://{value}"


def _load_files() -> list[tuple[str, bytes, str]]:
    payloads: list[tuple[str, bytes, str]] = []
    missing: list[str] = []
    for key, path, content_type in SEO_FILES:
        if not path.is_file():
            missing.append(str(path))
            continue
        payloads.append((key, path.read_bytes(), content_type))
    if missing:
        missing_list = ", ".join(missing)
        raise FileNotFoundError(f"Missing required static files: {missing_list}")
    return payloads


def _build_client():
    endpoint = _normalize_endpoint(_require_env("R2_ENDPOINT"))
    access_key = _require_env("R2_ACCESS_KEY_ID")
    secret_key = _require_env("R2_SECRET_ACCESS_KEY")
    region = _get_env("R2_REGION", "auto") or "auto"
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=botocore.config.Config(s3={"addressing_style": "path"}),
    )


def main() -> int:
    try:
        bucket = _require_env("R2_BUCKET")
        payloads = _load_files()
        client = _build_client()
        for key, body, content_type in payloads:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                CacheControl="public, max-age=3600",
            )
            print(f"Uploaded {key} -> s3://{bucket}/{key}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
