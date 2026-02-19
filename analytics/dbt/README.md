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
