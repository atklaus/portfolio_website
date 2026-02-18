import os
from typing import Any

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from app.layout import header
from shared.telemetry import page_guard


DBT_DOCS_BASE_URL_DEFAULT = "https://public.databuilds.dev/dbt_docs/latest"


def _get_docs_base_url() -> str:
    base = os.environ.get("DBT_DOCS_BASE_URL")
    if not base:
        try:
            base = st.secrets.get("DBT_DOCS_BASE_URL", "")
        except Exception:
            base = ""
    return (base or DBT_DOCS_BASE_URL_DEFAULT).rstrip("/")


def _get_elementary_base_url() -> str:
    base = os.environ.get("ELEMENTARY_BASE_URL")
    if not base:
        try:
            base = st.secrets.get("ELEMENTARY_BASE_URL", "")
        except Exception:
            base = ""
    return (base or "").rstrip("/")


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_required_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_optional_json(url: str) -> dict[str, Any] | None:
    try:
        response = requests.get(url, timeout=20)
    except requests.RequestException:
        return None
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _layer_for(node: dict[str, Any]) -> str:
    name = (node.get("name") or "").lower()
    schema = (node.get("schema") or "").lower()
    resource_type = node.get("resource_type") or ""
    if resource_type == "snapshot":
        return "snapshots"
    if resource_type == "seed":
        return "seeds"
    if name.startswith("stg_"):
        return "stg"
    if name.startswith("int_"):
        return "int"
    if schema == "marts" or name.startswith(("fct_", "dim_", "mart_")):
        return "marts"
    return "other"


def _build_lineage(manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, set[str]]]:
    nodes = manifest.get("nodes", {}) or {}
    sources = manifest.get("sources", {}) or {}
    all_entities = {**nodes, **sources}
    downstream_map: dict[str, set[str]] = {uid: set() for uid in all_entities}
    for uid, data in all_entities.items():
        for dep in data.get("depends_on", {}).get("nodes", []) or []:
            if dep in downstream_map:
                downstream_map[dep].add(uid)
    return nodes, all_entities, downstream_map


def _entity_label(entity: dict[str, Any], fallback: str) -> str:
    name = entity.get("name") or fallback
    resource = entity.get("resource_type") or ""
    return f"{name} ({resource})" if resource else name


def _columns_for(
    node_id: str,
    node: dict[str, Any],
    catalog: dict[str, Any] | None,
) -> list[dict[str, str]]:
    columns: list[dict[str, str]] = []
    catalog_nodes = (catalog or {}).get("nodes", {}) or {}
    catalog_entry = catalog_nodes.get(node_id)
    if catalog_entry:
        for key, col in (catalog_entry.get("columns") or {}).items():
            name = col.get("name") or key
            description = col.get("comment") or col.get("description") or ""
            columns.append({"name": name, "description": description})
        return columns

    for key, col in (node.get("columns") or {}).items():
        description = ""
        if isinstance(col, dict):
            description = col.get("description") or ""
        columns.append({"name": key, "description": description})
    return columns


def _bullet_list(items: list[str]) -> None:
    if not items:
        st.write("None")
        return
    lines = "\n".join(f"- {item}" for item in items)
    st.markdown(lines)


with page_guard(os.path.basename(__file__)):
    header.page_header("Analytics Ops", page_name=os.path.basename(__file__))

    st.markdown("dbt docs + lineage for this site")

    docs_base_url = _get_docs_base_url()
    manifest_url = f"{docs_base_url}/manifest.json"
    catalog_url = f"{docs_base_url}/catalog.json"
    run_results_url = f"{docs_base_url}/run_results.json"

    try:
        manifest = _fetch_required_json(manifest_url)
    except Exception as exc:
        st.error(f"Failed to load manifest.json from {manifest_url}: {exc}")
        st.stop()

    catalog = _fetch_optional_json(catalog_url)
    run_results = _fetch_optional_json(run_results_url)

    nodes, all_entities, downstream_map = _build_lineage(manifest)

    entries: list[dict[str, Any]] = []
    for uid, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in {"model", "seed", "snapshot"}:
            continue
        layer = _layer_for(node)
        upstream = node.get("depends_on", {}).get("nodes", []) or []
        downstream = list(downstream_map.get(uid, set()))
        entries.append(
            {
                "unique_id": uid,
                "model_name": node.get("name") or uid,
                "resource_type": resource_type,
                "package_name": node.get("package_name") or "",
                "schema": node.get("schema") or "",
                "materialization": (node.get("config") or {}).get("materialized") or "",
                "tags": ", ".join(node.get("tags") or []),
                "upstream_count": len(upstream),
                "downstream_count": len(downstream),
                "layer": layer,
            }
        )

    st.subheader("Run summary")
    if run_results is None:
        st.caption("run_results.json not available (ok).")
    else:
        metadata = run_results.get("metadata", {}) or {}
        generated_at = metadata.get("generated_at") or "unknown"
        results = run_results.get("results", []) or []
        total_exec_time = sum(result.get("execution_time") or 0 for result in results)
        failures = sum(1 for result in results if (result.get("status") or "") != "success")
        model_count = sum(1 for node in nodes.values() if node.get("resource_type") == "model")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Generated at", str(generated_at))
        c2.metric("Models", str(model_count))
        c3.metric("Total exec time (s)", f"{total_exec_time:.2f}")
        c4.metric("Failures/Errors", str(failures))

    models_tab, docs_tab, quality_tab = st.tabs(["Models", "Docs", "Quality"])

    with models_tab:
        st.subheader("Models")
        st.caption(f"Source: {docs_base_url}")

        left, right = st.columns([2, 1])
        search_term = left.text_input("Search model name", value="")
        layer_options = ["stg", "int", "marts", "snapshots", "seeds", "other"]
        selected_layers = right.multiselect("Layer", layer_options, default=layer_options)

        search_term = search_term.strip().lower()
        filtered = [
            entry
            for entry in entries
            if entry["layer"] in selected_layers
            and (not search_term or search_term in entry["model_name"].lower())
        ]

        if not filtered:
            st.info("No models match the current filters.")
        else:
            filtered = sorted(filtered, key=lambda item: item["model_name"])
            table = pd.DataFrame(
                [
                    {
                        "model_name": entry["model_name"],
                        "resource_type": entry["resource_type"],
                        "package_name": entry["package_name"],
                        "schema": entry["schema"],
                        "materialization": entry["materialization"],
                        "tags": entry["tags"],
                        "upstream_count": entry["upstream_count"],
                        "downstream_count": entry["downstream_count"],
                    }
                    for entry in filtered
                ]
            )
            st.dataframe(table, use_container_width=True, hide_index=True)

            show_details = st.checkbox("Show model details", value=False)
            if show_details:
                option_ids = [entry["unique_id"] for entry in filtered]
                label_map = {
                    entry["unique_id"]: f"{entry['model_name']} ({entry['package_name']})"
                    for entry in filtered
                }
                selected_id = st.selectbox(
                    "Select a model for details",
                    option_ids,
                    format_func=lambda uid: label_map.get(uid, uid),
                )

                node = nodes.get(selected_id, {})
                st.subheader("Model details")
                st.write(node.get("description") or "No description.")

                file_path = node.get("original_file_path") or node.get("path") or node.get("file_path") or ""
                if file_path:
                    st.code(file_path)

                upstream_ids = node.get("depends_on", {}).get("nodes", []) or []
                downstream_ids = sorted(downstream_map.get(selected_id, set()))

                st.markdown("**Upstream**")
                _bullet_list([_entity_label(all_entities.get(uid, {}), uid) for uid in upstream_ids])

                st.markdown("**Downstream**")
                _bullet_list([_entity_label(all_entities.get(uid, {}), uid) for uid in downstream_ids])

                columns = _columns_for(selected_id, node, catalog)
                if columns:
                    st.markdown("**Columns**")
                    st.dataframe(pd.DataFrame(columns), use_container_width=True, hide_index=True)

    with docs_tab:
        st.subheader("dbt docs")
        st.link_button("Open dbt docs in new tab", f"{docs_base_url}/index.html")
        components.iframe(f"{docs_base_url}/index.html", height=1000, scrolling=True)

    with quality_tab:
        st.subheader("Quality")
        elementary_base = _get_elementary_base_url()
        if not elementary_base:
            st.write("Elementary not configured yet.")
            st.caption("Set ELEMENTARY_BASE_URL to the hosted Elementary report location.")
        else:
            if elementary_base.endswith(".html"):
                elementary_url = elementary_base
            else:
                elementary_url = f"{elementary_base}/index.html"
            st.link_button("Open Elementary in new tab", elementary_url)
            components.iframe(elementary_url, height=1000, scrolling=True)
