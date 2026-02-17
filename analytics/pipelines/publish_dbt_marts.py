from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from lib.storage import put_bytes, put_file
from lib.storage.s3_compat import get_storage_config, is_configured

DEFAULT_DB_PATH = Path("analytics/artifacts/warehouse.duckdb")
DEFAULT_EXPORT_DIR = Path("analytics/artifacts/exports")

MODEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _default_run_id() -> str:
    return os.getenv("GITHUB_SHA") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_models(values: list[str]) -> list[str]:
    models: list[str] = []
    for value in values:
        for chunk in value.split(","):
            name = chunk.strip()
            if name:
                models.append(name)
    return models


def _quote_ident(part: str) -> str:
    return f'"{part.replace("\"", "\"\"")}"'


def _qualified_model(name: str) -> str:
    if not MODEL_RE.match(name):
        raise ValueError(
            f"Invalid model name '{name}'. Use letters, numbers, underscores, and optional schema prefix."
        )
    return ".".join(_quote_ident(part) for part in name.split("."))


def _export_model(con: duckdb.DuckDBPyConnection, model: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model_ref = _qualified_model(model)
    con.execute(
        f"COPY (SELECT * FROM {model_ref}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
        [str(out_path)],
    )


def _r2_key(project: str, model: str, run_id: str, latest: bool) -> str:
    base = f"analytics/{project}/marts/{model}"
    if latest:
        return f"{base}/latest/{model}.parquet"
    return f"{base}/runs/{run_id}/{model}.parquet"


def _write_manifest(project: str, run_id: str, models: list[str]) -> dict:
    built_at = datetime.now(timezone.utc).isoformat()
    entries = []
    for model in models:
        entries.append(
            {
                "name": model,
                "latest_key": _r2_key(project, model, run_id, latest=True),
            }
        )
    return {
        "run_id": run_id,
        "built_at": built_at,
        "models": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish dbt marts to R2.")
    parser.add_argument("--project", required=True, help="Project name for R2 key prefix.")
    parser.add_argument("--models", required=True, nargs="+", help="Model names (comma or space separated).")
    parser.add_argument("--run-id", default=None, help="Run identifier (defaults to GITHUB_SHA or UTC timestamp).")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to DuckDB file created by dbt.",
    )
    args = parser.parse_args()

    models = _parse_models(args.models)
    if not models:
        raise SystemExit("No models provided.")

    run_id = args.run_id or _default_run_id()

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"DuckDB file not found: {db_path}")

    if not is_configured(get_storage_config()):
        raise SystemExit("Storage is not configured. Set R2_* (or compatible) environment variables.")

    export_dir = DEFAULT_EXPORT_DIR / run_id
    con = duckdb.connect(str(db_path), read_only=True)

    uploaded_models: list[str] = []
    for model in models:
        out_path = export_dir / f"{model}.parquet"
        _export_model(con, model, out_path)

        run_key = _r2_key(args.project, model, run_id, latest=False)
        latest_key = _r2_key(args.project, model, run_id, latest=True)

        put_file(run_key, str(out_path), content_type="application/octet-stream")
        put_file(latest_key, str(out_path), content_type="application/octet-stream")
        uploaded_models.append(model)

    manifest = _write_manifest(args.project, run_id, uploaded_models)
    manifest_key = f"analytics/{args.project}/manifest/latest.json"
    put_bytes(
        manifest_key,
        json.dumps(manifest, indent=2).encode("utf-8"),
        content_type="application/json",
    )


if __name__ == "__main__":
    main()
