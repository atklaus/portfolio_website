{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}


select
  cast(ts as timestamp) as ts,
  cast(date as date) as date,
  event_name,
  page_id,
  session_id,
  trace_id,
  event_id,
  app_version,
  instance_id,
  user_agent,
  level,
  message,
  schema_version,
  payload_json,
  source_file,
  ingested_at
from {{ source('raw', 'website_events') }}
