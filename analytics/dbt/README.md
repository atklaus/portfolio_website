# dbt DuckDB Analytics

This dbt project can run locally with no R2/Iceberg secrets. Iceberg models
only run when the `iceberg` target is selected.

Quick start (local, no secrets required):

```bash
cd analytics/dbt
dbt build --profiles-dir . --target local --exclude tag:iceberg
```

CI/Iceberg run (requires R2/Iceberg env vars):

```bash
cd analytics/dbt
dbt build --profiles-dir . --target iceberg
```

## Querying Submissions

After `dbt build --target iceberg`, query `r2_iceberg.analytics.telemetry_submissions`:

```sql
select
  submitted_at,
  page_slug,
  session_id,
  visitor_id,
  submission_id,
  fields,
  tags
from r2_iceberg.analytics.telemetry_submissions
where page_slug = 'wnba_success'
order by submitted_at desc
limit 100;
```

Daily adoption view:

```sql
select
  date,
  page_slug,
  submissions_count,
  unique_visitors_count
from r2_iceberg.analytics.telemetry_submission_daily
order by date desc, page_slug;
```

## Sessions lineage

`fct_sessions_daily` now exposes both lineage paths:

- `active_sessions_from_snapshots` (from `stg_website_sessions`)
- `active_sessions_from_events` (from `stg_website_events`)
- `sessions` (snapshot-first with event fallback)
- `sessions_source` (`session_snapshots` or `events`)

Parity check model:

```sql
select *
from r2_iceberg.analytics.fct_sessions_daily_comparison
order by date desc
limit 30;
```

Latest source objects seen by staging:

```sql
select *
from r2_iceberg.analytics.dbg_telemetry_source_latest_files
order by dataset, max_ingested_at desc
limit 40;
```
