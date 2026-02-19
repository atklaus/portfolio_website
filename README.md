# DataBuilds.dev

Interactive data engineering + ML experiments powered by Streamlit, DuckDB, dbt, and object storage.

Production site: https://databuilds.dev

- Streamlit app with multiple project UIs
- Cloudflare R2 artifact + telemetry storage
- dbt-duckdb transformations for analytics marts
- CI-driven batch pipelines + artifact publishing
- Production deploy on Fly.io

## Architecture (High Level)

```
                 ┌─────────────────────────┐
                 │ GitHub Actions          │
                 │ (Nightly + Manual Runs) │
                 └────────────┬────────────┘
                              │
                              ▼
                     analytics/dbt + pipelines
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Cloudflare R2           │
                 │ - telemetry events      │
                 │ - events parquet layer  │
                 │ - session rollups       │
                 │ - feature tables        │
                 │ - serving marts         │
                 └────────────┬────────────┘
                              │
                              ▼
                 ┌─────────────────────────┐
                 │ Streamlit App (Fly.io)  │
                 │ - reads Parquet         │
                 │ - DuckDB query layer    │
                 │ - cached model loads    │
                 └─────────────────────────┘
```

## Repository Structure

app.py              → Streamlit entrypoint
pages/              → App pages (manually controlled navigation)
projects/           → Individual project UIs
layout/             → Shared UI components
static/             → Static assets
lib/storage/        → R2 abstraction utilities
analytics/
├── dbt/             → dbt-duckdb project (transform layer)
├── pipelines/       → Batch jobs + artifact publishing
└── artifacts/       → Local build outputs (gitignored)
.github/workflows/   → CI + analytics automation
Dockerfile           → Runtime container (no dbt installed)
fly.toml             → Fly.io config

The runtime app does not execute dbt or heavy transformations.
All compute-heavy operations happen in GitHub Actions and publish artifacts to R2.

## Runtime vs Batch Architecture

Runtime app:
- Lightweight
- Reads precomputed Parquet from R2
- Uses DuckDB for querying
- Loads ML models with caching

Batch layer:
- dbt transforms raw data into marts
- Pipelines export Parquet artifacts
- Artifacts are versioned + published to R2
- Triggered via GitHub Actions

This separation is intentional to keep the production container lean and predictable.

## Telemetry Storage

Raw telemetry events are written as JSONL.gz for fast, low-latency writes:

- `telemetry/events/date=YYYY-MM-DD/events_*.jsonl.gz`

Nightly, a GitHub Actions pipeline converts raw events into partitioned Parquet for fast reads:

- `telemetry/events_parquet/date=YYYY-MM-DD/part-0000.parquet`
- `telemetry/events_parquet/date=YYYY-MM-DD/_manifest.json`

The admin analytics page queries Parquet by default and falls back to JSONL.gz if a date
has not been rolled up yet. To keep latency and listing costs low, limit JSONL queries to
the last 7 days and retain only the required raw history.

### Submission Tracking (Per Page)

Submission telemetry is configured per page in `shared/telemetry/config.py` under
`TELEMETRY_SUBMISSION_TRACKING`.

Each page slug can define:
- `event_name`: emitted event type (usually `submission`)
- `allowed_fields`: explicit whitelist of fields to log
- `redaction_rules`: per-field rules (`keep`, `hash`, `drop`, `bucketize`)
- `dedupe_window_seconds`: rerun dedupe window to prevent duplicate emits

To add tracking to a page:
1. Add a page config entry keyed by page slug in `shared/telemetry/config.py`.
2. Call `track_submission(page_id=..., form_id=..., inputs=..., tags=...)` only at the form/button submit point.
3. Keep `inputs` minimal and explicit; only allowlisted fields are persisted.

## Local Development

### Run the app

```bash
poetry install
poetry run streamlit run app.py
```

Requires `R2_*` env vars (or fallback local mode for storage-dependent pages).

Analytics deps require:

```bash
poetry install --with analytics
```

## Running Analytics Locally

### Run dbt locally

```bash
cd analytics/dbt
dbt run
dbt test
```

Publish marts to R2:

```bash
poetry run python analytics/pipelines/publish_dbt_marts.py \
  --project databuilds \
  --models mart_example
```

This writes Parquet artifacts and a manifest JSON to R2.

## Deployment

- Push to `master`
- GitHub Actions runs tests
- Fly deploys the new image
- Analytics workflow runs separately on a schedule or manual trigger

## Design Principles

- Precompute heavy transformations
- Serve immutable artifacts
- Keep runtime container lean
- Separate compute from presentation
- Prefer object storage over embedded databases
- Cache aggressively at runtime
