# Landscape Image Prediction Update

Date: 2026-02-25

## What changed
- Reworked `pages/1_landscape_img.py` into a two-column product-style layout with:
  - compact hero header + runtime pill
  - card-style upload/preview and results panels
  - top prediction, top-5 probability table, and bar chart
  - `Explain` and `Performance` expanders
- Added `projects/landscape_img/inference.py` to isolate inference logic:
  - deterministic full-image coverage with edge-aligned overlapping tiles
  - aspect-preserving resize to bound compute
  - single decode path and explicit preprocess/inference/postprocess helpers
- Kept model loading cached with `st.cache_resource` and switched to `compile=False` load for lower startup latency.

## Why
- Improve UI balance and readability while preserving global nav/header behavior.
- Ensure preprocessing is intentional and covers the full image (instead of potentially skipping edges).
- Reduce repeated work and expose timing instrumentation to debug latency bottlenecks.
