# Telemetry Audit

## Scope
Audit target: Streamlit telemetry/event/session flow for `databuilds.dev` with focus on `wnba_success`.

## Phase 1: Audit

### 1) Telemetry Code Paths

Active page entrypoints:
- `shared/telemetry/telemetry.py:page_guard`
- `shared/telemetry/telemetry.py:instrument_page`
- `shared/telemetry/telemetry.py:log_event`
- `shared/telemetry/telemetry.py:track_submission`
- `pages/2_wnba_success.py` calls `track_submission(...)` at the submit button (`Predict Success`).

Event write paths (runtime):
- `shared/telemetry/telemetry.py:_flush_events` -> sink fanout.
- `shared/telemetry/sinks.py:SpacesSink.write_events` -> `lib/storage/io.py:put_bytes` -> object key from `lib/storage/paths.py:telemetry_events_key`.
- `shared/telemetry/sinks.py:LocalSink.write_events` -> local gz JSONL mirror.
- `shared/telemetry/sinks.py:StdoutSink.write_events` -> stdout.

Session snapshot write paths (runtime):
- `shared/telemetry/telemetry.py:_flush_session_snapshot` -> sink fanout.
- `shared/telemetry/sinks.py:SpacesSink.write_session` -> parquet temp file -> `put_file(...)` -> `telemetry_sessions_key(...)`.
- `shared/telemetry/sinks.py:LocalSink.write_session` -> local parquet.

Analytics/transform write paths:
- `analytics/pipelines/build_events_parquet.py` reads `telemetry/events/date=*/events_*.jsonl.gz`, normalizes via `lib/telemetry/schema.py`, writes `telemetry/events_parquet/date=YYYY-MM-DD/part-*.parquet`.
- `scripts/load_telemetry_to_iceberg.py` loads parquet into Iceberg raw tables (`r2_iceberg.raw.website_events`, `r2_iceberg.raw.website_sessions` if available).

Legacy/dormant telemetry path (not used by pages):
- `shared/logging/telemetry.py` writes local `data/logs/...` JSONL/parquet.
- `shared/logging/ops.py:R2LogHandler.flush` writes operational app logs to `ops/logs/...` (separate from telemetry events).

### 2) Current Logging Model

#### Event model (runtime)
- Shape emitted by `shared/telemetry/telemetry.py:log_event`:
  - `ts_utc`, `session_id`, `visitor_id`, `page`, `page_slug`, `event_type`, `event_name`, `duration_ms`, `payload`, `app_version`, optional `trace_id`.
- Runtime buffering:
  - In-memory `st.session_state["telemetry_buffer"]`.
  - Flush when `len(buffer) >= LOG_FLUSH_EVENTS` (default `25`) or every `LOG_FLUSH_SECONDS` (default `5`).
- Object format:
  - newline-delimited JSON, gzip compressed (`.jsonl.gz`).
- Event key/partition:
  - `telemetry/events/date=YYYY-MM-DD/events_{session_id}_{HHMMSS}_{rand}.jsonl.gz`.

#### Session model (runtime)
- Session identifiers/stats tracked in `shared/telemetry/session.py`:
  - `session_id` (stable in Streamlit session_state across reruns).
  - `visitor_id` (best-effort hashed browser fingerprint fallback to random).
  - `pages_visited`, `event_count`, `error_count`, `total_runtime_ms`, `last_page`.
- Snapshot writes:
  - parquet to `telemetry/sessions/date=YYYY-MM-DD/sessions_{session_id}.parquet`.
  - Triggered by periodic flush interval (`LOG_SESSION_FLUSH_SECONDS`, default `60`) and certain events.

#### Submission model
- `pages/2_wnba_success.py` submit button calls `track_submission(page_id="wnba_success", form_id="predict", ...)`.
- Submission payload is page-configured via `shared/telemetry/config.py:TELEMETRY_SUBMISSION_TRACKING`:
  - `event_name`
  - `allowed_fields`
  - `redaction_rules`
  - `dedupe_window_seconds`
- Dedupe guard (`shared/telemetry/submission.py:mark_submission_if_new`) suppresses immediate rerun duplicates.

### 3) Storage Targets and Config

Storage config source:
- `lib/storage/s3_compat.py:get_storage_config`.
- Provider precedence: `R2_*` -> `SPACES_*` -> `S3_*`.

Primary telemetry env vars/secrets:
- `R2_BUCKET`, `R2_ENDPOINT`, `R2_REGION`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
- Sink/telemetry controls:
  - `LOGGING_ENABLED`
  - `LOG_SINK` (`stdout`, `local`, `r2`/`spaces`/`s3`, combinations like `stdout+r2`)
  - `LOG_FLUSH_EVENTS`, `LOG_FLUSH_SECONDS`, `LOG_SESSION_FLUSH_SECONDS`, `LOG_MAX_BUFFER`

Environment behavior:
- If `LOG_SINK` includes object storage and credentials are missing, object sink is disabled.
- Default sink:
  - `stdout+r2` when storage creds are configured.
  - `stdout` otherwise.
- Local development can force local files with `LOG_SINK=local`.

### Flow Diagram

Event flow:
- Page interaction (button/form/page render)
- `page_guard`/`track_submission`/`log_event`
- `st.session_state` in-memory buffer
- `_flush_events`
- `SpacesSink.write_events` (or local/stdout sink)
- Object key: `telemetry/events/date=.../events_*.jsonl.gz`
- Nightly/parquet job -> `telemetry/events_parquet/date=.../part-*.parquet`
- Iceberg load -> `r2_iceberg.raw.website_events`

Session snapshot flow:
- Event handling updates counters/pages/session metadata
- `_flush_session_snapshot`
- `SpacesSink.write_session` (parquet)
- Object key: `telemetry/sessions/date=.../sessions_{session_id}.parquet`
- Optional Iceberg load (if session parquet prefix matches loader config)

### Direct Answer: Do we already capture submission data in events?

Yes for `wnba_success`.
- Source: `pages/2_wnba_success.py` calls `track_submission(...)` on submit.
- Emitted event:
  - `event_type`/`event_name`: `submission`
  - `page`/`page_slug`: `wnba_success`
  - Includes `session_id`, `visitor_id`, timestamp, and structured submission payload (`payload.fields`, `payload.submission_id`, etc.).

What was missing/unclear before this pass:
- Session snapshots were written to `telemetry/sessions/...` but the Iceberg loader default expected `telemetry/sessions_parquet/...`, so downstream session tables could appear empty even when runtime snapshots existed.
- Submission payload structure was previously less query-friendly; now it is explicit and page-config driven.

## Phase 2: Design Choice

Chosen approach: **A) submission events + optional session rollups**.

Why:
- Minimal change to current architecture (event pipeline already working).
- DuckDB/dbt-friendly because submissions are standard events with `event_name='submission'`.
- Avoids adding separate session-file semantics for each app page.
- Session rollups remain available as optional enrichment, not required for submission observability.

## Phase 3: Implemented for `wnba_success`

Implemented:
- Config-driven submission tracking (`shared/telemetry/config.py`).
- Structured submission payload + per-field redaction hooks (`shared/telemetry/submission.py`).
- Stable `session_id` + best-effort `visitor_id` in event/session records.
- Rerun idempotency guard to prevent duplicate submit emits.
- Validation test:
  - `tests/test_telemetry_submission.py` simulates submit, checks required fields, confirms key partition pattern.
