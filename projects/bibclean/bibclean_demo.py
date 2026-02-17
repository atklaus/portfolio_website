"""Lightweight, line-by-line demo script for bibclean.

Run this file in VS Code and execute line-by-line or selection.
"""
from pathlib import Path

import pandas as pd

from projects.bibclean.apply.scopus_apply import apply_mapping_to_scopus
from projects.bibclean.apply.wos_apply import apply_mapping_to_wos_records
from projects.bibclean.canonicalize import canonicalize_references
from projects.bibclean import config
from projects.bibclean.io.detect import detect_input_format
from projects.bibclean.io.scopus_csv import extract_scopus_references, load_scopus_csv
from projects.bibclean.io.wos_plaintext import extract_wos_references, parse_wos_plaintext, write_wos_plaintext
from projects.bibclean.merge import compute_canonical_doc_id, merge_documents
from projects.bibclean.io.scopus_csv import build_documents_from_scopus
from projects.bibclean.io.wos_plaintext import build_documents_from_wos


# --- Inputs (hardcoded) ---
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "projects" / "bibclean" / "fixtures"
SCOPUS_PATH = FIXTURES_DIR / "scopus_sample.csv"
WOS_PATH = FIXTURES_DIR / "wos_sample.txt"
OUTPUT_DIR = FIXTURES_DIR / "bibclean_demo"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# --- Mode A: Scopus ---
fmt_scopus = detect_input_format(str(SCOPUS_PATH))
print("Scopus format:", fmt_scopus)

df_scopus, ref_col = load_scopus_csv(str(SCOPUS_PATH))
raw_refs_scopus = extract_scopus_references(df_scopus, ref_col)

mapping_df_scopus, summary_scopus, mapping_dict_scopus, review_pairs_scopus = canonicalize_references(
    raw_refs_scopus,
    return_review_pairs=True,
)
print("Scopus summary:", summary_scopus)

cleaned_scopus = apply_mapping_to_scopus(df_scopus, ref_col, mapping_dict_scopus)
scopus_out = OUTPUT_DIR / "scopus_cleaned.csv"
cleaned_scopus.to_csv(scopus_out, index=False)

mapping_out_scopus = OUTPUT_DIR / "scopus_reference_mapping.csv"
mapping_df_scopus.to_csv(mapping_out_scopus, index=False)
review_out_scopus = OUTPUT_DIR / "scopus_review_pairs.csv"
review_pairs_scopus.to_csv(review_out_scopus, index=False)


# --- Mode A: WoS ---
fmt_wos = detect_input_format(str(WOS_PATH))
print("WoS format:", fmt_wos)

wos_file = parse_wos_plaintext(str(WOS_PATH))
raw_refs_wos = extract_wos_references(wos_file.records)

mapping_df_wos, summary_wos, mapping_dict_wos, review_pairs_wos = canonicalize_references(
    raw_refs_wos,
    return_review_pairs=True,
)
print("WoS summary:", summary_wos)

updated_records = apply_mapping_to_wos_records(wos_file.records, mapping_dict_wos)
wos_file.records = updated_records

wos_out = OUTPUT_DIR / "wos_cleaned.txt"
write_wos_plaintext(str(wos_out), wos_file)

mapping_out_wos = OUTPUT_DIR / "wos_reference_mapping.csv"
mapping_df_wos.to_csv(mapping_out_wos, index=False)
review_out_wos = OUTPUT_DIR / "wos_review_pairs.csv"
review_pairs_wos.to_csv(review_out_wos, index=False)


# --- Mode B: Merge + clean ---
scopus_docs = build_documents_from_scopus(df_scopus, ref_col)
wos_docs = build_documents_from_wos(wos_file.records)

canonical_docs, doc_mappings = merge_documents(scopus_docs + wos_docs)
print("Mode B canonical docs:", len(canonical_docs))

canonical_ids = {idx: compute_canonical_doc_id(doc) for idx, doc in enumerate(canonical_docs)}

# Document mapping output
rows = []
for mapping in doc_mappings:
    rows.append(
        {
            "raw_doc_id": mapping.raw_doc_id,
            "canonical_doc_id": canonical_ids[mapping.canonical_index],
            "match_reason": mapping.match_reason,
            "confidence": mapping.confidence,
        }
    )

doc_map_df = pd.DataFrame(rows)
doc_map_out = OUTPUT_DIR / "document_mapping.csv"
doc_map_df.to_csv(doc_map_out, index=False)

# Canonicalize refs across merged docs
merged_raw_refs = []
for doc in canonical_docs:
    merged_raw_refs.extend(doc.references)

merged_mapping_df, merged_summary, merged_mapping_dict, merged_review_pairs = canonicalize_references(
    merged_raw_refs,
    auto_merge_threshold=config.merged_auto_merge_threshold,
    return_review_pairs=True,
)
print("Mode B summary:", merged_summary)

# Emit merged Scopus-like CSV
merged_rows = []
for doc in canonical_docs:
    mapped_refs = [merged_mapping_dict.get(ref, ref) for ref in doc.references]
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
merged_out = OUTPUT_DIR / "merged_scopus.csv"
merged_df.to_csv(merged_out, index=False)

merged_ref_map_out = OUTPUT_DIR / "merged_reference_mapping.csv"
merged_mapping_df.to_csv(merged_ref_map_out, index=False)
merged_review_out = OUTPUT_DIR / "merged_review_pairs.csv"
merged_review_pairs.to_csv(merged_review_out, index=False)

print("Wrote outputs to", OUTPUT_DIR)
