import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st

from app.layout.header import page_header
from app.shared_ui import st_utils as stu

from projects.bibclean import config as bc_config
from projects.bibclean.apply.scopus_apply import apply_mapping_to_scopus
from projects.bibclean.apply.wos_apply import apply_mapping_to_wos_records
from projects.bibclean.canonicalize import canonicalize_references
from projects.bibclean.io.detect import detect_input_format
from projects.bibclean.io.scopus_csv import (
from shared.telemetry import page_guard

with page_guard(os.path.basename(__file__)):
        build_documents_from_scopus,
        extract_scopus_references,
        load_scopus_csv,
    )
    from projects.bibclean.io.wos_plaintext import (
        WosFile,
        build_documents_from_wos,
        extract_wos_references,
        parse_wos_plaintext,
        write_wos_plaintext,
    )
    from projects.bibclean.match.cluster import UnionFind
    from projects.bibclean.merge import compute_canonical_doc_id, merge_documents
    from projects.bibclean.normalize.parse import extract_doi



    page_header("Bibliometrix Reference Cleaner", page_name=os.path.basename(__file__))

    st.markdown("## Bibliometrix Reference Cleaner")
    st.caption(
        "Clean and consolidate references from Scopus or Web of Science so they import cleanly into "
        "bibliometrix/Biblioshiny."
    )


    @contextmanager
    def _temp_config(overrides: dict):
        originals = {key: getattr(bc_config, key) for key in overrides}
        for key, value in overrides.items():
            setattr(bc_config, key, value)
        try:
            yield
        finally:
            for key, value in originals.items():
                setattr(bc_config, key, value)


    def _init_state():
        if "bibclean" not in st.session_state:
            st.session_state["bibclean"] = {
                "stage": "idle",
                "mode": "Mode A",
                "settings": {},
                "outputs": {},
                "review_df": None,
                "artifacts": {},
            }
        return st.session_state["bibclean"]


    def _default_settings():
        return {
            "auto_merge_threshold":85,
            "review_threshold": 85,
            "max_candidates": 50,
            "structured_override": True,
            "initials_normalization": True,
            "verbose": False,
            "doc_merge_threshold": int(bc_config.doc_merge_threshold),
            "journal_match_bonus": int(bc_config.journal_match_bonus),
            "boilerplate_tokens_raw": ", ".join(bc_config.boilerplate_tokens),
        }


    def _get_settings(state):
        if not state.get("settings"):
            state["settings"] = _default_settings()
        return state["settings"]


    class _PseudoUpload:
        def __init__(self, name: str, data: bytes):
            self.name = name
            self._data = data

        def getvalue(self) -> bytes:
            return self._data


    def _set_sample(sample_type: str):
        st.session_state["bibclean_sample"] = sample_type


    def _clear_sample():
        st.session_state.pop("bibclean_sample", None)


    def _get_sample_upload():
        sample_type = st.session_state.get("bibclean_sample")
        if not sample_type:
            return None
        root_dir = Path(__file__).resolve().parents[1]
        fixtures_dir = root_dir / "projects" / "bibclean" / "fixtures"
        if sample_type == "scopus":
            path = fixtures_dir / "scopus_sample.csv"
        else:
            path = fixtures_dir / "wos_sample.txt"
        if not path.exists():
            return None
        return _PseudoUpload(path.name, path.read_bytes())


    def _preview_upload(upload) -> dict:
        temp_path = _write_upload_to_temp(upload)
        file_format = detect_input_format(temp_path)
        if file_format == "scopus_csv":
            df, ref_col = load_scopus_csv(temp_path)
            docs = len(df)
            ref_instances = None
            if ref_col:
                try:
                    ref_instances = len(extract_scopus_references(df, ref_col))
                except Exception:
                    ref_instances = None
            return {
                "name": upload.name,
                "format": "Scopus CSV",
                "docs": docs,
                "refs": ref_instances,
            }

        wos_file = parse_wos_plaintext(temp_path)
        docs = len(wos_file.records)
        ref_instances = None
        try:
            raw_records = [list(record) for record in wos_file.records]
            ref_instances = len(extract_wos_references(raw_records))
        except Exception:
            ref_instances = None
        return {
            "name": upload.name,
            "format": "WoS Plaintext",
            "docs": docs,
            "refs": ref_instances,
        }


    def _render_preview(previews):
        st.markdown(
            """
    <style>
    .bibclean-card {
        border: 1px solid rgba(120, 120, 120, 0.2);
        border-radius: 10px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.75rem;
        background: rgba(255, 255, 255, 0.03);
    }
    .bibclean-card h4 {
        margin: 0 0 0.4rem 0;
        font-size: 0.95rem;
    }
    .bibclean-badge {
        display: inline-block;
        padding: 0.15rem 0.5rem;
        border-radius: 999px;
        font-size: 0.75rem;
        border: 1px solid rgba(120, 120, 120, 0.35);
    }
    .bibclean-metric {
        font-size: 0.85rem;
        opacity: 0.8;
    }
    </style>
    """,
            unsafe_allow_html=True,
        )
        for preview in previews:
            ref_val = preview.get("refs")
            st.markdown(
                f"""
    <div class="bibclean-card">
      <h4>{preview.get("name", "Uploaded file")}</h4>
      <div class="bibclean-badge">{preview['format']}</div>
      <div style="margin-top: 0.6rem; display: flex; gap: 1.5rem; flex-wrap: wrap;">
        <div class="bibclean-metric"><strong>Docs</strong><br>{preview['docs']}</div>
        <div class="bibclean-metric"><strong>Raw refs</strong><br>{ref_val if ref_val is not None else '—'}</div>
      </div>
    </div>
    """,
                unsafe_allow_html=True,
            )


    def _reset_state():
        st.session_state.pop("bibclean", None)
        _clear_sample()
        st.rerun()


    def _write_upload_to_temp(uploaded_file) -> str:
        suffix = Path(uploaded_file.name).suffix
        handle, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(handle, "wb") as f:
            f.write(uploaded_file.getvalue())
        return path


    def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
        return df.to_csv(index=False).encode("utf-8")


    def _json_to_bytes(payload: dict) -> bytes:
        return json.dumps(payload, indent=2).encode("utf-8")


    def _wos_to_bytes(wos_file) -> bytes:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.close()
        write_wos_plaintext(tmp.name, wos_file)
        with open(tmp.name, "rb") as f:
            return f.read()


    def _build_outputs_list(entries):
        outputs = []
        for entry in entries:
            if entry["data"] is None:
                continue
            outputs.append(entry)
        return outputs


    def _apply_review_merges(mapping_df: pd.DataFrame, review_df: pd.DataFrame) -> pd.DataFrame:
        ref_list = mapping_df["raw_reference"].tolist()
        ref_index = {ref: idx for idx, ref in enumerate(ref_list)}

        uf = UnionFind(len(ref_list))
        for cluster_id, group in mapping_df.groupby("cluster_id"):
            indices = [ref_index[ref] for ref in group["raw_reference"].tolist()]
            if len(indices) > 1:
                base = indices[0]
                for idx in indices[1:]:
                    uf.union(base, idx)

        merge_pairs = review_df[review_df["decision"] == "Merge"]
        for _, row in merge_pairs.iterrows():
            a = ref_index.get(row["raw_reference_a"])
            b = ref_index.get(row["raw_reference_b"])
            if a is None or b is None:
                continue
            uf.union(a, b)

        clusters = {}
        for idx in range(len(ref_list)):
            root = uf.find(idx)
            clusters.setdefault(root, []).append(idx)

        canonical_by_root = {}
        for root, indices in clusters.items():
            refs = [ref_list[i] for i in indices]
            doi_refs = [ref for ref in refs if extract_doi(ref)]
            if doi_refs:
                canonical = doi_refs[0]
            else:
                canonical = max(refs, key=len)
            canonical_by_root[root] = canonical

        cluster_order = sorted(canonical_by_root.items(), key=lambda item: item[1])
        cluster_id_by_root = {root: i + 1 for i, (root, _) in enumerate(cluster_order)}

        rows = []
        for idx, ref in enumerate(ref_list):
            root = uf.find(idx)
            canonical = canonical_by_root[root]
            cluster_id = cluster_id_by_root[root]
            row = mapping_df.loc[mapping_df["raw_reference"] == ref].iloc[0].to_dict()
            row["canonical_reference"] = canonical
            row["cluster_id"] = cluster_id
            if row["reason"] == "unique" and canonical != ref:
                row["reason"] = "manual_needed"
            rows.append(row)

        updated = pd.DataFrame(rows)
        return updated.sort_values("raw_reference").reset_index(drop=True)


    def _render_outputs(outputs):
        st.markdown("### Downloads")
        left, right = st.columns(2)

        def _label_for(entry):
            filename = entry["filename"].lower()
            if "merged_cleaned" in filename or filename.endswith("cleaned.csv") or filename.endswith("cleaned.txt"):
                return "Cleaned file"
            if "reference_mapping" in filename:
                return "Reference mapping"
            if "review_pairs" in filename:
                return "Review pairs"
            if "summary" in filename:
                return "Summary"
            if "document_mapping" in filename:
                return "Document mapping"
            return entry["label"].replace("Download ", "")

        cleaned_entries = []
        other_entries = []
        for entry in outputs:
            filename = entry["filename"].lower()
            if "cleaned" in filename:
                cleaned_entries.append(entry)
            else:
                other_entries.append(entry)

        with left:
            st.markdown("**Cleaned output**")
            for entry in cleaned_entries:
                st.download_button(
                    _label_for(entry),
                    data=entry["data"],
                    file_name=entry["filename"],
                    mime=entry.get("mime", "application/octet-stream"),
                    key=entry["key"],
                    use_container_width=True,
                    type="primary",
                )

        with right:
            st.markdown("**Supporting files**")
            for entry in other_entries:
                st.download_button(
                    _label_for(entry),
                    data=entry["data"],
                    file_name=entry["filename"],
                    mime=entry.get("mime", "application/octet-stream"),
                    key=entry["key"],
                    use_container_width=True,
                )


    def _render_tab_flow(mode_label: str, uploaded_files: list, state: dict):
        settings = _get_settings(state)

        st.divider()
        st.markdown("### 2) ⚙️ Configure")
        with st.form(f"bibclean_settings_{mode_label.replace(' ', '_')}"):
            col1, col2 = st.columns(2)
            with col1:
                auto_merge_threshold = st.slider(
                    "Auto-merge confidence (%)",
                    min_value=0,
                    max_value=100,
                    value=int(settings["auto_merge_threshold"]),
                    step=1,
                    help="Higher values merge fewer references automatically.",
                )
            with col2:
                review_threshold = st.slider(
                    "Manual review threshold (%)",
                    min_value=0,
                    max_value=100,
                    value=int(settings["review_threshold"]),
                    step=1,
                    help="Candidates around this threshold show up in the review table.",
                )

            with st.expander("Advanced settings", expanded=False):
                max_candidates = st.number_input(
                    "Max candidates per reference",
                    min_value=5,
                    max_value=200,
                    value=settings["max_candidates"],
                    step=5,
                    help="Limits comparisons per block for speed.",
                )
                structured_override = st.toggle(
                    "Structured override",
                    value=settings["structured_override"],
                    help="Boosts confidence if year + volume + page match.",
                )
                initials_normalization = st.toggle(
                    "Initials normalization",
                    value=settings["initials_normalization"],
                    help="Joins initials like 'M E J' → 'MEJ' to improve matching.",
                )
                verbose = st.toggle(
                    "Verbose diagnostics",
                    value=settings["verbose"],
                    help="Shows the full reference mapping table.",
                )
                doc_merge_threshold = st.number_input(
                    "Document merge threshold (Mode B)",
                    min_value=50,
                    max_value=100,
                    value=settings["doc_merge_threshold"],
                    step=1,
                    help="Higher values merge fewer documents.",
                )
                journal_match_bonus = st.number_input(
                    "Journal match bonus",
                    min_value=0,
                    max_value=10,
                    value=settings["journal_match_bonus"],
                    step=1,
                    help="Adds a small confidence bonus when normalized journals match.",
                )
                boilerplate_tokens_raw = st.text_input(
                    "Boilerplate tokens (comma-separated)",
                    value=settings["boilerplate_tokens_raw"],
                    help="Tokens removed during normalization (e.g., vol, pp).",
                )

            saved = st.form_submit_button("Save settings")

        if saved:
            settings = {
                "auto_merge_threshold": auto_merge_threshold,
                "review_threshold": review_threshold,
                "max_candidates": max_candidates,
                "structured_override": structured_override,
                "initials_normalization": initials_normalization,
                "verbose": verbose,
                "doc_merge_threshold": int(doc_merge_threshold),
                "journal_match_bonus": int(journal_match_bonus),
                "boilerplate_tokens_raw": boilerplate_tokens_raw,
            }
            state["settings"] = settings
            st.caption("Settings saved.")

        st.button(
            "Start over",
            on_click=_reset_state,
            key=f"bibclean_start_over_{mode_label}",
        )

        st.divider()
        st.markdown("### 3) ▶️ Run")
        st.caption("Runs using the last saved settings.")

        run_disabled = not uploaded_files
        run_clicked = st.button(
            "Run cleaning",
            key=f"bibclean_run_{mode_label}",
            type="primary",
            use_container_width=True,
            disabled=run_disabled,
        )
        if run_disabled:
            st.info("Upload at least one file to enable Run.")

        settings = _get_settings(state)
        auto_merge_threshold = settings["auto_merge_threshold"]
        review_threshold = settings["review_threshold"]
        max_candidates = settings["max_candidates"]
        structured_override = settings["structured_override"]
        initials_normalization = settings["initials_normalization"]
        verbose = settings["verbose"]
        doc_merge_threshold = settings["doc_merge_threshold"]
        journal_match_bonus = settings["journal_match_bonus"]
        boilerplate_tokens_raw = settings["boilerplate_tokens_raw"]

        if run_clicked:
            if not uploaded_files:
                st.warning("Please upload at least one file.")
            else:
                state["mode"] = mode_label
                with st.status("Running bibclean…", expanded=True) as status:
                    status.update(label="Writing uploads", state="running")
                    tmp_paths = []
                    for upload in uploaded_files:
                        if upload is None:
                            continue
                        tmp_paths.append(_write_upload_to_temp(upload))

                    overrides = {
                        "max_candidates_per_ref": int(max_candidates),
                        "doc_merge_threshold": int(doc_merge_threshold),
                        "journal_match_bonus": int(journal_match_bonus),
                        "boilerplate_tokens": [
                            tok.strip() for tok in boilerplate_tokens_raw.split(",") if tok.strip()
                        ],
                        "enable_structured_override": structured_override,
                        "enable_initials_normalization": initials_normalization,
                    }

                    with _temp_config(overrides):
                        if mode_label == "Mode A":
                            status.update(label="Detecting format + extracting references", state="running")
                            input_path = tmp_paths[0]
                            file_format = detect_input_format(input_path)

                            status.update(label="Matching + clustering", state="running")
                            if file_format == "scopus_csv":
                                df, ref_col = load_scopus_csv(input_path)
                                raw_refs = extract_scopus_references(df, ref_col)
                                mapping_df, summary, mapping_dict, review_pairs_df = canonicalize_references(
                                    raw_refs,
                                    auto_merge_threshold=auto_merge_threshold,
                                    review_threshold=review_threshold,
                                    return_review_pairs=True,
                                )
                                summary["input_format"] = "scopus_csv"
                                summary["document_count"] = len(df)
                                cleaned_df = apply_mapping_to_scopus(df, ref_col, mapping_dict)

                                cleaned_bytes = _df_to_csv_bytes(cleaned_df)
                                cleaned_name = f"{Path(uploaded_files[0].name).stem}_cleaned.csv"
                                outputs = _build_outputs_list(
                                    [
                                        {
                                            "label": "Download cleaned CSV",
                                            "data": cleaned_bytes,
                                            "filename": cleaned_name,
                                            "mime": "text/csv",
                                            "key": f"bibclean_download_cleaned_{mode_label}",
                                        },
                                        {
                                            "label": "Download reference_mapping.csv",
                                            "data": _df_to_csv_bytes(mapping_df),
                                            "filename": "reference_mapping.csv",
                                            "mime": "text/csv",
                                            "key": f"bibclean_download_mapping_{mode_label}",
                                        },
                                        {
                                            "label": "Download summary.json",
                                            "data": _json_to_bytes(summary),
                                            "filename": "summary.json",
                                            "mime": "application/json",
                                            "key": f"bibclean_download_summary_{mode_label}",
                                        },
                                        {
                                            "label": "Download review_pairs.csv",
                                            "data": _df_to_csv_bytes(review_pairs_df),
                                            "filename": "review_pairs.csv",
                                            "mime": "text/csv",
                                            "key": f"bibclean_download_review_{mode_label}",
                                        },
                                    ]
                                )

                                state["artifacts"] = {
                                    "mode": "A",
                                    "format": "scopus_csv",
                                    "df": df,
                                    "ref_col": ref_col,
                                }

                            else:
                                wos_file = parse_wos_plaintext(input_path)
                                raw_records = [list(record) for record in wos_file.records]
                                header_lines = list(wos_file.header_lines)
                                raw_refs = extract_wos_references(raw_records)
                                mapping_df, summary, mapping_dict, review_pairs_df = canonicalize_references(
                                    raw_refs,
                                    auto_merge_threshold=auto_merge_threshold,
                                    review_threshold=review_threshold,
                                    return_review_pairs=True,
                                )
                                summary["input_format"] = "wos_plaintext"
                                summary["document_count"] = len(raw_records)
                                wos_file_clean = WosFile(
                                    header_lines=header_lines,
                                    records=apply_mapping_to_wos_records(raw_records, mapping_dict),
                                )

                                cleaned_bytes = _wos_to_bytes(wos_file_clean)
                                cleaned_name = f"{Path(uploaded_files[0].name).stem}_cleaned.txt"
                                outputs = _build_outputs_list(
                                    [
                                        {
                                            "label": "Download cleaned plaintext",
                                            "data": cleaned_bytes,
                                            "filename": cleaned_name,
                                            "mime": "text/plain",
                                            "key": f"bibclean_download_cleaned_{mode_label}",
                                        },
                                        {
                                            "label": "Download reference_mapping.csv",
                                            "data": _df_to_csv_bytes(mapping_df),
                                            "filename": "reference_mapping.csv",
                                            "mime": "text/csv",
                                            "key": f"bibclean_download_mapping_{mode_label}",
                                        },
                                        {
                                            "label": "Download summary.json",
                                            "data": _json_to_bytes(summary),
                                            "filename": "summary.json",
                                            "mime": "application/json",
                                            "key": f"bibclean_download_summary_{mode_label}",
                                        },
                                        {
                                            "label": "Download review_pairs.csv",
                                            "data": _df_to_csv_bytes(review_pairs_df),
                                            "filename": "review_pairs.csv",
                                            "mime": "text/csv",
                                            "key": f"bibclean_download_review_{mode_label}",
                                        },
                                    ]
                                )

                                state["artifacts"] = {
                                    "mode": "A",
                                    "format": "wos_plaintext",
                                    "wos_records": raw_records,
                                    "wos_header_lines": header_lines,
                                }

                        else:
                            status.update(label="Detecting formats + merging documents", state="running")
                            documents = []
                            for path in tmp_paths:
                                file_format = detect_input_format(path)
                                if file_format == "scopus_csv":
                                    df, ref_col = load_scopus_csv(path)
                                    documents.extend(build_documents_from_scopus(df, ref_col))
                                else:
                                    wos_file = parse_wos_plaintext(path)
                                    documents.extend(build_documents_from_wos(wos_file.records))

                            canonical_docs, doc_mappings = merge_documents(documents)
                            canonical_ids = {
                                idx: compute_canonical_doc_id(doc)
                                for idx, doc in enumerate(canonical_docs)
                            }

                            doc_rows = []
                            for mapping in doc_mappings:
                                doc_rows.append(
                                    {
                                        "raw_doc_id": mapping.raw_doc_id,
                                        "canonical_doc_id": canonical_ids[mapping.canonical_index],
                                        "match_reason": mapping.match_reason,
                                        "confidence": mapping.confidence,
                                    }
                                )

                            doc_mapping_df = pd.DataFrame(doc_rows)

                            raw_refs = []
                            for doc in canonical_docs:
                                raw_refs.extend(doc.references)

                            status.update(label="Matching + clustering", state="running")
                            mapping_df, summary, mapping_dict, review_pairs_df = canonicalize_references(
                                raw_refs,
                                auto_merge_threshold=auto_merge_threshold,
                                review_threshold=review_threshold,
                                return_review_pairs=True,
                            )
                            summary["document_merge"] = {
                                "doc_merge_threshold": bc_config.doc_merge_threshold,
                                "total_documents": len(documents),
                                "canonical_documents": len(canonical_docs),
                            }

                            merged_rows = []
                            for doc in canonical_docs:
                                mapped_refs = [mapping_dict.get(ref, ref) for ref in doc.references]
                                merged_rows.append(
                                    {
                                        "Title": doc.title,
                                        "Year": doc.year or "",
                                        "DOI": doc.doi or "",
                                        "Authors": doc.authors,
                                        "References": "; ".join(mapped_refs),
                                    }
                                )

                            merged_df = pd.DataFrame(merged_rows)
                            status.update(label="Preparing downloads", state="running")
                            outputs = _build_outputs_list(
                                [
                                    {
                                        "label": "Download merged_cleaned.csv",
                                        "data": _df_to_csv_bytes(merged_df),
                                        "filename": "merged_cleaned.csv",
                                        "mime": "text/csv",
                                        "key": f"bibclean_download_merged_{mode_label}",
                                    },
                                    {
                                        "label": "Download document_mapping.csv",
                                        "data": _df_to_csv_bytes(doc_mapping_df),
                                        "filename": "document_mapping.csv",
                                        "mime": "text/csv",
                                        "key": f"bibclean_download_docmap_{mode_label}",
                                    },
                                    {
                                        "label": "Download reference_mapping.csv",
                                        "data": _df_to_csv_bytes(mapping_df),
                                        "filename": "reference_mapping.csv",
                                        "mime": "text/csv",
                                        "key": f"bibclean_download_mapping_{mode_label}",
                                    },
                                    {
                                        "label": "Download summary.json",
                                        "data": _json_to_bytes(summary),
                                        "filename": "summary.json",
                                        "mime": "application/json",
                                        "key": f"bibclean_download_summary_{mode_label}",
                                    },
                                    {
                                        "label": "Download review_pairs.csv",
                                        "data": _df_to_csv_bytes(review_pairs_df),
                                        "filename": "review_pairs.csv",
                                        "mime": "text/csv",
                                        "key": f"bibclean_download_review_{mode_label}",
                                    },
                                ]
                            )

                            state["artifacts"] = {
                                "mode": "B",
                                "canonical_docs": canonical_docs,
                                "doc_mapping_df": doc_mapping_df,
                            }

                    state["outputs"] = {
                        "mapping_df": mapping_df,
                        "mapping_dict": mapping_dict,
                        "summary": summary,
                        "review_pairs_df": review_pairs_df,
                        "download_entries": outputs,
                    }
                    state["review_df"] = None
                    state["stage"] = "processed"
                    status.update(label="Done", state="complete")

        if state["stage"] in {"processed", "reviewed"} and state.get("mode") == mode_label:
            st.divider()
            st.markdown("### ✅ Results")
            summary = state["outputs"]["summary"]
            doc_merge = summary.get("document_merge", {})
            docs = summary.get("document_count", 0)
            if mode_label == "Mode B":
                docs = doc_merge.get("total_documents", 0)

            metrics = [
                ("Docs", docs),
                ("Refs", summary.get("total_reference_instances", 0)),
                ("Unique refs", summary.get("unique_reference_count", 0)),
                ("Clusters", summary.get("clusters", 0)),
                ("Auto merged", summary.get("auto_merged_clusters", 0)),
                ("Review pairs", summary.get("review_pair_count", 0)),
            ]
            if mode_label == "Mode B":
                metrics.append(("Canonical docs", doc_merge.get("canonical_documents", 0)))

            cols = st.columns(min(len(metrics), 6))
            for idx, (label, value) in enumerate(metrics[:6]):
                cols[idx].metric(label, value)
            if len(metrics) > 6:
                extra_cols = st.columns(len(metrics) - 6)
                for idx, (label, value) in enumerate(metrics[6:]):
                    extra_cols[idx].metric(label, value)

            _render_outputs(state["outputs"]["download_entries"])

            review_pairs_df = state["outputs"]["review_pairs_df"]
            if review_pairs_df is not None and not review_pairs_df.empty:
                st.markdown("### Manual review")
                min_conf = st.slider(
                    "Min confidence",
                    0,
                    100,
                    value=int(review_threshold),
                    key=f"bibclean_min_conf_{mode_label}",
                )
                search = st.text_input(
                    "Search references",
                    key=f"bibclean_review_search_{mode_label}",
                )

                if state["review_df"] is None:
                    review_df = review_pairs_df.copy()
                    if "confidence" in review_df.columns:
                        review_df["decision"] = review_df["confidence"].apply(
                            lambda c: "Merge" if c >= auto_merge_threshold - 2 else "Not sure"
                        )
                    else:
                        review_df["decision"] = "Not sure"
                    state["review_df"] = review_df
                else:
                    review_df = state["review_df"]

                filtered_df = review_df
                if "confidence" in filtered_df.columns:
                    filtered_df = filtered_df[filtered_df["confidence"] >= min_conf]
                if search:
                    search_lower = search.lower()
                    mask = pd.Series(False, index=filtered_df.index)
                    if "raw_reference_a" in filtered_df.columns:
                        mask = mask | filtered_df["raw_reference_a"].str.contains(search_lower, na=False)
                    if "raw_reference_b" in filtered_df.columns:
                        mask = mask | filtered_df["raw_reference_b"].str.contains(search_lower, na=False)
                    filtered_df = filtered_df[mask]

                display_cols = [
                    col
                    for col in [
                        "raw_reference_a",
                        "raw_reference_b",
                        "confidence",
                        "reason",
                        "decision",
                    ]
                    if col in filtered_df.columns
                ]
                display_df = filtered_df[display_cols]

                editor_col, _ = st.columns([3, 1])
                with editor_col:
                    edited = st.data_editor(
                        display_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "decision": st.column_config.SelectboxColumn(
                                "Decision",
                                options=["Merge", "Keep separate", "Not sure"],
                                required=True,
                            )
                        },
                        key=f"bibclean_review_editor_{mode_label}",
                    )
                if "decision" in edited.columns:
                    review_df.loc[edited.index, "decision"] = edited["decision"]
                state["review_df"] = review_df

                if st.button(
                    "Apply review decisions",
                    key=f"bibclean_apply_review_{mode_label}",
                ):
                    updated_mapping = _apply_review_merges(state["outputs"]["mapping_df"], review_df)
                    mapping_dict = dict(
                        zip(
                            updated_mapping["raw_reference"],
                            updated_mapping["canonical_reference"],
                        )
                    )

                    artifacts = state["artifacts"]
                    outputs = []
                    if artifacts.get("mode") == "A":
                        if artifacts.get("format") == "scopus_csv":
                            df = artifacts["df"]
                            ref_col = artifacts["ref_col"]
                            cleaned_df = apply_mapping_to_scopus(df, ref_col, mapping_dict)
                            outputs = _build_outputs_list(
                                [
                                    {
                                        "label": "Download cleaned CSV",
                                        "data": _df_to_csv_bytes(cleaned_df),
                                        "filename": "cleaned.csv",
                                        "mime": "text/csv",
                                        "key": f"bibclean_download_cleaned_review_{mode_label}",
                                    },
                                    {
                                        "label": "Download reference_mapping.csv",
                                        "data": _df_to_csv_bytes(updated_mapping),
                                        "filename": "reference_mapping.csv",
                                        "mime": "text/csv",
                                        "key": f"bibclean_download_mapping_review_{mode_label}",
                                    },
                                    {
                                        "label": "Download summary.json",
                                        "data": _json_to_bytes(summary),
                                        "filename": "summary.json",
                                        "mime": "application/json",
                                        "key": f"bibclean_download_summary_review_{mode_label}",
                                    },
                                ]
                            )
                        else:
                            raw_records = artifacts["wos_records"]
                            header_lines = artifacts.get("wos_header_lines", [])
                            wos_file_clean = WosFile(
                                header_lines=header_lines,
                                records=apply_mapping_to_wos_records(raw_records, mapping_dict),
                            )
                            outputs = _build_outputs_list(
                                [
                                    {
                                        "label": "Download cleaned plaintext",
                                        "data": _wos_to_bytes(wos_file_clean),
                                        "filename": "cleaned.txt",
                                        "mime": "text/plain",
                                        "key": f"bibclean_download_cleaned_review_{mode_label}",
                                    },
                                    {
                                        "label": "Download reference_mapping.csv",
                                        "data": _df_to_csv_bytes(updated_mapping),
                                        "filename": "reference_mapping.csv",
                                        "mime": "text/csv",
                                        "key": f"bibclean_download_mapping_review_{mode_label}",
                                    },
                                    {
                                        "label": "Download summary.json",
                                        "data": _json_to_bytes(summary),
                                        "filename": "summary.json",
                                        "mime": "application/json",
                                        "key": f"bibclean_download_summary_review_{mode_label}",
                                    },
                                ]
                            )
                    else:
                        canonical_docs = artifacts["canonical_docs"]
                        doc_mapping_df = artifacts["doc_mapping_df"]
                        merged_rows = []
                        for doc in canonical_docs:
                            mapped_refs = [mapping_dict.get(ref, ref) for ref in doc.references]
                            merged_rows.append(
                                {
                                    "Title": doc.title,
                                    "Year": doc.year or "",
                                    "DOI": doc.doi or "",
                                    "Authors": doc.authors,
                                    "References": "; ".join(mapped_refs),
                                }
                            )
                        merged_df = pd.DataFrame(merged_rows)
                        outputs = _build_outputs_list(
                            [
                                {
                                    "label": "Download merged_cleaned.csv",
                                    "data": _df_to_csv_bytes(merged_df),
                                    "filename": "merged_cleaned.csv",
                                    "mime": "text/csv",
                                    "key": f"bibclean_download_merged_review_{mode_label}",
                                },
                                {
                                    "label": "Download document_mapping.csv",
                                    "data": _df_to_csv_bytes(doc_mapping_df),
                                    "filename": "document_mapping.csv",
                                    "mime": "text/csv",
                                    "key": f"bibclean_download_docmap_review_{mode_label}",
                                },
                                {
                                    "label": "Download reference_mapping.csv",
                                    "data": _df_to_csv_bytes(updated_mapping),
                                    "filename": "reference_mapping.csv",
                                    "mime": "text/csv",
                                    "key": f"bibclean_download_mapping_review_{mode_label}",
                                },
                                {
                                    "label": "Download summary.json",
                                    "data": _json_to_bytes(summary),
                                    "filename": "summary.json",
                                    "mime": "application/json",
                                    "key": f"bibclean_download_summary_review_{mode_label}",
                                },
                            ]
                        )

                    state["outputs"]["mapping_df"] = updated_mapping
                    state["outputs"]["mapping_dict"] = mapping_dict
                    state["outputs"]["download_entries"] = outputs
                    state["review_df"] = review_df
                    state["stage"] = "reviewed"
                    st.success("Review decisions applied.")

            with st.expander("Diagnostics", expanded=False):
                st.json(summary)
                if verbose:
                    st.dataframe(state["outputs"]["mapping_df"], use_container_width=True)


    state = _init_state()
    settings = _get_settings(state)

    tab_a, tab_b, tab_c = st.tabs(
        ["Mode A: Clean one export", "Mode B: Merge + clean", "How cleaning works"]
    )

    uploaded_file_a = None
    uploaded_files_b = []

    with tab_a:
        st.markdown("### 1) 📤 Upload")
        st.caption("Mode A cleans references within a single Scopus or WoS export.")
        sample_cols = st.columns(2)
        if sample_cols[0].button("Load sample Scopus", key="bibclean_sample_scopus"):
            _set_sample("scopus")
        if sample_cols[1].button("Load sample WoS", key="bibclean_sample_wos"):
            _set_sample("wos")

        uploaded_file_a = st.file_uploader(
            "Upload a Scopus CSV or WoS plaintext file",
            type=["csv", "txt"],
            key="bibclean_single_upload",
        )
        if uploaded_file_a is not None:
            _clear_sample()

        sample_upload = _get_sample_upload()
        preview_upload = sample_upload or uploaded_file_a
        if sample_upload and uploaded_file_a is None:
            st.info(f"Using sample file: {sample_upload.name}")
        if preview_upload is not None:
            _render_preview([_preview_upload(preview_upload)])
        uploaded_files_a = (
            [sample_upload]
            if sample_upload is not None
            else ([uploaded_file_a] if uploaded_file_a is not None else [])
        )
        _render_tab_flow("Mode A", uploaded_files_a, state)

    with tab_b:
        st.markdown("### 1) 📤 Upload")
        st.caption("Mode B merges duplicate documents across files, then cleans references.")
        uploaded_files_b = st.file_uploader(
            "Upload one or more Scopus/WoS files",
            type=["csv", "txt"],
            accept_multiple_files=True,
            key="bibclean_multi_upload",
        )
        if uploaded_files_b:
            _clear_sample()
            previews = []
            for upload in uploaded_files_b:
                previews.append(_preview_upload(upload))
            _render_preview(previews)
        _render_tab_flow("Mode B", uploaded_files_b or [], state)

    with tab_c:
        st.markdown("### What bibclean does")
        st.markdown(
            """
    In short: it standardizes messy citation strings so equivalent references collapse into a single,
    canonical form, ready for bibliometrix or Biblioshiny.

    **1) Detect and parse**
    - The uploaded file is automatically detected (Scopus CSV or WoS plaintext).
    - Documents and reference fields are extracted into a consistent internal format so they can be compared reliably.

    **2) Normalize references**
    - Boilerplate tokens are removed (for example, “vol”, “pp”, punctuation noise).
    - Author names and initials are standardized (optional).
    - Structured fields like year, volume, and page are identified when possible.
    - This reduces surface-level variation without changing meaning.

    **3) Generate candidate matches**
    - Groups references into logical “blocks”.
    - Only compares references that are likely to match.
    - This keeps the process fast even for large exports.

    **4) Score and cluster**
    - Similarity scores are computed between likely matches.
    - References that are similar enough are grouped into clusters.
    - Each cluster represents one real-world citation expressed in multiple slightly different ways.

    **5) Canonicalize**
    - A single canonical reference is selected.
    - If a DOI is present, it is preferred.
    - Otherwise, the most complete reference is chosen.
    - All equivalent references are mapped to this canonical version.

    **6) Review (optional)**
    - References near your review threshold are surfaced.
    - You can:
      - Merge them manually
      - Keep them separate
    - Manual decisions override automatic clustering without re-running the full process.

    **7) Outputs**
    - A cleaned export ready for bibliometrix/Biblioshiny
    - `reference_mapping.csv` (original → canonical mapping)
    - `summary.json` (metrics and configuration)
    - `review_pairs.csv` (if review candidates exist)
    """
        )
        st.caption(
            "Tuning tip: Higher auto-merge confidence means fewer automatic merges (more conservative). "
            "Higher review threshold means fewer references shown for manual review."
        )
