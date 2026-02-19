{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

{% set events_rel = none %}
{% set event_cols = [] %}
{% if execute %}
  {% set events_rel = adapter.get_relation(database='r2_iceberg', schema='raw', identifier='website_events') %}
  {% if events_rel is not none %}
    {% for col in adapter.get_columns_in_relation(events_rel) %}
      {% do event_cols.append(col.name | lower) %}
    {% endfor %}
  {% endif %}
{% endif %}

{% if execute and events_rel is none %}
select
  cast(null as timestamp) as ts,
  cast(null as timestamp) as occurred_at,
  cast(null as date) as date,
  cast(null as varchar) as event_name,
  cast(null as varchar) as page_id,
  cast(null as varchar) as page_slug,
  cast(null as varchar) as session_id,
  cast(null as varchar) as visitor_id,
  cast(null as varchar) as trace_id,
  cast(null as varchar) as submission_id,
  cast(null as timestamp) as submitted_at,
  cast(null as bigint) as submission_number_in_session,
  cast(null as json) as fields,
  cast(null as json) as tags,
  cast(null as varchar) as event_id,
  cast(null as varchar) as app_version,
  cast(null as varchar) as git_sha,
  cast(null as varchar) as instance_id,
  cast(null as varchar) as user_agent,
  cast(null as varchar) as level,
  cast(null as varchar) as message,
  cast(null as integer) as schema_version,
  cast(null as varchar) as payload_json,
  cast(null as varchar) as source_file,
  cast(null as timestamp) as ingested_at,
  cast(null as date) as ingestion_date
where false
{% else %}
with source_events as (
  select
    cast(ts as timestamp) as ts,
    cast(ts as timestamp) as occurred_at,
    cast(date as date) as date,
    event_name,
    page_id,
    session_id,
    {% if 'visitor_id' in event_cols %}
    visitor_id,
    {% else %}
    cast(null as varchar) as visitor_id,
    {% endif %}
    trace_id,
    {% if 'submission_id' in event_cols %}
    submission_id,
    {% else %}
    cast(null as varchar) as submission_id,
    {% endif %}
    event_id,
    app_version,
    {% if 'git_sha' in event_cols %}
    git_sha,
    {% else %}
    cast(null as varchar) as git_sha,
    {% endif %}
    instance_id,
    user_agent,
    level,
    message,
    schema_version,
    payload_json,
    source_file,
    cast(ingested_at as timestamp) as ingested_at
  from {{ source('raw', 'website_events') }}
),
parsed as (
  select
    *,
    try_cast(payload_json as json) as payload_obj
  from source_events
)
select
  ts,
  occurred_at,
  coalesce(date, cast(occurred_at as date)) as date,
  event_name,
  page_id,
  coalesce(
    nullif(trim(page_id), ''),
    nullif(trim(json_extract_string(payload_obj, '$.page_slug')), ''),
    nullif(trim(json_extract_string(payload_obj, '$.page_id')), '')
  ) as page_slug,
  coalesce(
    nullif(trim(session_id), ''),
    nullif(trim(json_extract_string(payload_obj, '$.session_id')), '')
  ) as session_id,
  coalesce(
    nullif(trim(visitor_id), ''),
    nullif(trim(json_extract_string(payload_obj, '$.visitor_id')), '')
  ) as visitor_id,
  trace_id,
  coalesce(
    nullif(trim(submission_id), ''),
    nullif(trim(json_extract_string(payload_obj, '$.submission_id')), ''),
    nullif(trim(trace_id), '')
  ) as submission_id,
  coalesce(
    try_cast(json_extract_string(payload_obj, '$.submitted_at') as timestamp),
    occurred_at
  ) as submitted_at,
  try_cast(
    coalesce(
      nullif(trim(json_extract_string(payload_obj, '$.submission_number_in_session')), ''),
      nullif(trim(json_extract_string(payload_obj, '$.submission_index')), '')
    ) as bigint
  ) as submission_number_in_session,
  json_extract(payload_obj, '$.fields') as fields,
  json_extract(payload_obj, '$.tags') as tags,
  event_id,
  app_version,
  coalesce(
    nullif(trim(git_sha), ''),
    nullif(trim(json_extract_string(payload_obj, '$.git_sha')), '')
  ) as git_sha,
  instance_id,
  user_agent,
  level,
  message,
  schema_version,
  payload_json,
  source_file,
  ingested_at,
  cast(ingested_at as date) as ingestion_date
from parsed
{% endif %}
