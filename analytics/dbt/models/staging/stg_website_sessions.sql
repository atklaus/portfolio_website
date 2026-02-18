{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}


select
  cast(ts_utc as timestamp) as ts_utc,
  cast(date as date) as date,
  session_id,
  pages_visited,
  cast(event_count as bigint) as event_count,
  cast(error_count as bigint) as error_count,
  cast(total_runtime_ms as bigint) as total_runtime_ms,
  app_version,
  last_page,
  source_file,
  ingested_at
from {{ source('raw', 'website_sessions') }}
