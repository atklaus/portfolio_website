import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from app.layout import header
from shared.telemetry import page_guard
from shared.settings import get_settings


DBT_DOCS_BASE_URL_DEFAULT = "https://public.databuilds.dev/dbt_docs/latest"
GX_DOCS_BASE_URL_DEFAULT = "https://public.databuilds.dev/gx/latest"


def _get_docs_base_url() -> str:
    base = os.environ.get("DBT_DOCS_BASE_URL")
    if not base:
        try:
            base = st.secrets.get("DBT_DOCS_BASE_URL", "")
        except Exception:
            base = ""
    return (base or DBT_DOCS_BASE_URL_DEFAULT).rstrip("/")


def _get_gx_docs_base_url() -> str:
    base = os.environ.get("GX_DOCS_BASE_URL")
    if not base:
        try:
            base = st.secrets.get("GX_DOCS_BASE_URL", "")
        except Exception:
            base = ""
    return (base or GX_DOCS_BASE_URL_DEFAULT).rstrip("/")


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


@st.cache_data(ttl=300, show_spinner=False)
def _url_available(url: str) -> bool:
    try:
        response = requests.head(url, timeout=5, allow_redirects=True)
        if response.status_code < 400:
            return True
    except requests.RequestException:
        return False
    try:
        response = requests.get(url, timeout=5, stream=True)
        return response.status_code < 400
    except requests.RequestException:
        return False


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


def _format_generated_at(value: str) -> str:
    if not value or value == "unknown":
        return "Unknown"
    try:
        cleaned = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local_time = parsed.astimezone()
        day = local_time.strftime("%d").lstrip("0")
        hour = local_time.strftime("%I").lstrip("0") or "0"
        return f"{local_time.strftime('%b')} {day}, {local_time.strftime('%Y')} {hour}:{local_time.strftime('%M %p')}"
    except Exception:
        return str(value)


def _format_exec_time(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    if seconds < 1:
        ms = seconds * 1000
        if ms < 10:
            return f"{ms:.1f}ms"
        return f"{ms:.0f}ms"
    if seconds < 10:
        return f"{seconds:.2f}s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


with page_guard(os.path.basename(__file__)):
    header.page_header("Analytics Ops", page_name=os.path.basename(__file__))

    settings = get_settings()
    github_profile_url = settings.github_url
    linkedin_profile_url = settings.linkedin_url

    st.markdown(
        """
        <style>
        .dp-scope {
          max-width: 1180px;
          margin: 0 auto 0.75rem auto;
        }
        .dp-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1.5rem;
          padding: 0.35rem 0 0.55rem 0;
          border-bottom: 1px solid rgba(155, 231, 216, 0.16);
        }
        .dp-title {
          font-size: 1.6rem;
          font-weight: 700;
          color: var(--ads-ink);
          margin: 0 0 0.15rem 0;
        }
        .dp-subtitle {
          font-size: 0.95rem;
          color: var(--ads-muted);
          margin: 0;
        }
        .dp-actions {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
        }
        .dp-stats {
          margin: 0.8rem 0 0.55rem 0;
        }
        .dp-stat-card {
          border-radius: 14px;
          padding: 0.85rem 0.95rem;
          border: 1px solid rgba(155, 231, 216, 0.16);
          background: rgba(255, 255, 255, 0.04);
          min-height: 86px;
        }
        .dp-stat-label {
          font-size: 0.74rem;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: rgba(178, 200, 195, 0.75);
          margin-bottom: 0.4rem;
        }
        .dp-stat-value {
          font-size: 1.25rem;
          font-weight: 600;
          color: var(--ads-ink);
        }
        .dp-stat-value--muted {
          color: rgba(178, 200, 195, 0.7);
        }
        .dp-stat-value--alert {
          color: #ffb3a7;
        }
        .dp-scope [data-testid="stExpander"] > details {
          border-radius: 12px;
          border: 1px solid rgba(155, 231, 216, 0.12);
          background: rgba(255, 255, 255, 0.02);
        }
        .dp-scope [data-testid="stExpander"] summary {
          font-size: 0.9rem;
        }
        .dp-source-link {
          display: inline-flex;
          align-items: center;
          gap: 0.4rem;
          font-size: 0.82rem;
          font-weight: 600;
          color: var(--ads-ink);
          text-decoration: none;
          border-radius: 999px;
          padding: 0.3rem 0.7rem;
          border: 1px solid rgba(155, 231, 216, 0.28);
          background: rgba(155, 231, 216, 0.12);
        }
        .dp-source-link:hover {
          border-color: rgba(155, 231, 216, 0.6);
          background: rgba(155, 231, 216, 0.2);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="dp-scope">', unsafe_allow_html=True)
    header_html = f"""
    <div class="dp-header">
      <div>
        <div class="dp-title">Analytics Ops</div>
        <div class="dp-subtitle">dbt docs + lineage powering this site</div>
      </div>
      <div class="dp-actions">
        <a class="ads-icon-btn" href="/" target="_self" rel="noopener" aria-label="Home"><i class="fas fa-home"></i></a>
        <a class="ads-icon-btn" href="{github_profile_url}" target="_blank" rel="noopener" aria-label="GitHub"><i class="fas fa-code"></i></a>
        <a class="ads-icon-btn" href="{linkedin_profile_url}" target="_blank" rel="noopener" aria-label="LinkedIn"><i class="fab fa-linkedin"></i></a>
      </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

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

    def _stat_card(label: str, value: str, value_class: str = "") -> str:
        value_classes = " ".join(item for item in ["dp-stat-value", value_class] if item)
        return f"""
        <div class="dp-stat-card">
          <div class="dp-stat-label">{label}</div>
          <div class="{value_classes}">{value}</div>
        </div>
        """

    if run_results is None:
        generated_at_raw = "unknown"
        generated_at_display = "Unknown"
        exec_time_display = "—"
        failures = None
    else:
        metadata = run_results.get("metadata", {}) or {}
        generated_at_raw = metadata.get("generated_at") or "unknown"
        generated_at_display = _format_generated_at(str(generated_at_raw))
        results = run_results.get("results", []) or []
        total_exec_time = sum(result.get("execution_time") or 0 for result in results)
        exec_time_display = _format_exec_time(total_exec_time)
        failures = sum(1 for result in results if (result.get("status") or "") != "success")

    model_count = sum(1 for node in nodes.values() if node.get("resource_type") == "model")

    st.markdown('<div class="dp-stats">', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(_stat_card("Generated", generated_at_display), unsafe_allow_html=True)
    c2.markdown(_stat_card("Models", str(model_count)), unsafe_allow_html=True)
    c3.markdown(_stat_card("Exec time", exec_time_display), unsafe_allow_html=True)
    if failures is None:
        failures_value = "—"
        failures_class = "dp-stat-value--muted"
    elif failures == 0:
        failures_value = "0"
        failures_class = "dp-stat-value--muted"
    else:
        failures_value = str(failures)
        failures_class = "dp-stat-value--alert"
    c4.markdown(_stat_card("Failures", failures_value, failures_class), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Run details"):
        st.markdown(f"**Generated at (raw):** `{generated_at_raw}`")
        invocation_id = None
        if run_results is not None:
            invocation_id = (run_results.get("metadata", {}) or {}).get("invocation_id")
        if invocation_id:
            st.markdown(f"**Invocation id:** `{invocation_id}`")
        st.markdown(
            f'<a class="dp-source-link" href="{docs_base_url}" target="_blank" rel="noopener">Source</a>',
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    models_tab, docs_tab, quality_tab = st.tabs(["Models", "Docs", "Quality"])

    with models_tab:
        left, right = st.columns([2, 3])
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
        st.link_button("Open dbt docs in new tab", f"{docs_base_url}/index.html")
        components.iframe(f"{docs_base_url}/index.html", height=1000, scrolling=True)

    with quality_tab:
        gx_base_url = _get_gx_docs_base_url()
        gx_index_url = f"{gx_base_url}/index.html"
        if _url_available(gx_index_url):
            st.link_button("Open GX docs in new tab", gx_index_url)
            components.iframe(gx_index_url, height=1000, scrolling=True)
        else:
            st.write("Great Expectations docs not available yet (last run may have failed).")
