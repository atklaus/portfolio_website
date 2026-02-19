# Telemetry Paths: App -> R2 -> Iceberg -> dbt

## Canonical R2 prefixes

- Raw runtime events (append-only JSONL.gz): `telemetry/events/`
- Analytics events parquet landing zone: `telemetry/events_parquet/`
- Session snapshots parquet: `telemetry/sessions/`

## What dbt reads

dbt models in `analytics/dbt` read **Iceberg tables**, not raw object prefixes directly:

- `source('raw', 'website_events')` -> `r2_iceberg.raw.website_events`
- `source('raw', 'website_sessions')` -> `r2_iceberg.raw.website_sessions`

Those raw Iceberg tables are populated by `scripts/load_telemetry_to_iceberg.py`.

## Prefix mapping used by Iceberg loader

Events dataset (`website_events`):

- Primary/default: `telemetry/events_parquet/`
- Config:
  - `TELEMETRY_EVENTS_PARQUET_PREFIX` (single prefix)
  - `TELEMETRY_EVENTS_PARQUET_PREFIXES` (comma-separated, overrides single)
- Intentional behavior: dbt does **not** read `telemetry/events/` JSONL directly.

Sessions dataset (`website_sessions`):

- Primary/default: `telemetry/sessions/`
- Backward-compatible legacy prefix also scanned by default: `telemetry/sessions_parquet/`
- Config:
  - `TELEMETRY_SESSIONS_PARQUET_PREFIX` (single primary prefix)
  - `TELEMETRY_SESSIONS_PARQUET_PREFIXES` (comma-separated, overrides defaults)

## Session metric lineage

- `analytics.stg_website_sessions`: canonicalized session snapshots (deduped by `session_id + snapshot_at`)
- `analytics.fct_sessions_daily`:
  - `active_sessions_from_snapshots` = distinct sessions from snapshot telemetry
  - `active_sessions_from_events` = distinct sessions from event telemetry
  - `sessions` = snapshot-derived when available per day, otherwise event-derived fallback
  - `sessions_source` indicates which source supplied `sessions`
- `analytics.fct_sessions_daily_comparison`: daily parity check between snapshot-derived and event-derived counts.

