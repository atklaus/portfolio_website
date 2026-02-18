from __future__ import annotations

import os
import shutil
from pathlib import Path


def _copy_site(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    gx_root = repo_root / "analytics" / "great_expectations"
    artifacts_root = repo_root / "analytics" / "artifacts"
    gx_site = artifacts_root / "gx" / "site"
    gx_output = artifacts_root / "gx"

    duckdb_path = os.environ.get("DBT_DUCKDB_PATH")
    if not duckdb_path:
        duckdb_path = str(artifacts_root / "warehouse.duckdb")
        os.environ["DBT_DUCKDB_PATH"] = duckdb_path

    duckdb_path_obj = Path(duckdb_path)
    if duckdb_path_obj.is_absolute():
        conn_path = duckdb_path_obj.as_posix().lstrip("/")
        gx_conn = f"duckdb:////{conn_path}"
    else:
        gx_conn = f"duckdb:///{duckdb_path}"
    os.environ.setdefault("GX_DUCKDB_CONN", gx_conn)

    try:
        from great_expectations.data_context import FileDataContext
    except Exception as exc:
        print(f"GX import failed: {exc}")
        return 0

    try:
        context = FileDataContext(context_root_dir=str(gx_root))
    except TypeError:
        try:
            context = FileDataContext(str(gx_root))
        except Exception as exc:
            print(f"GX context init failed: {exc}")
            return 0
    except Exception as exc:
        try:
            from great_expectations.data_context import get_context

            context = get_context(context_root_dir=str(gx_root))
        except Exception as inner_exc:
            print(f"GX context init failed: {inner_exc}")
            return 0

    try:
        context.run_checkpoint(checkpoint_name="hsqi_checkpoint")
    except Exception as exc:
        print(f"GX checkpoint failed: {exc}")

    try:
        context.build_data_docs()
    except Exception as exc:
        print(f"GX data docs build failed: {exc}")
        return 0

    if not gx_site.exists():
        fallback = gx_root / "uncommitted" / "data_docs" / "local_site"
        if fallback.exists():
            gx_site = fallback
        else:
            print("GX data docs site not found.")
            return 0

    try:
        _copy_site(gx_site, gx_output)
    except Exception as exc:
        print(f"GX site copy failed: {exc}")
        return 0

    if (gx_output / "index.html").exists():
        print(f"GX docs ready at {gx_output}")
    else:
        print("GX docs generated but index.html not found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
