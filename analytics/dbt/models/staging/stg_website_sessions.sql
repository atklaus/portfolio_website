{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

{% set sessions_rel = none %}
{% set session_cols = [] %}
{% if execute %}
  {% set sessions_rel = adapter.get_relation(database='r2_iceberg', schema='raw', identifier='website_sessions') %}
  {% if sessions_rel is not none %}
    {% for col in adapter.get_columns_in_relation(sessions_rel) %}
      {% do session_cols.append(col.name | lower) %}
    {% endfor %}
  {% endif %}
{% endif %}

{% if execute and sessions_rel is none %}
select
  cast(null as timestamp) as ts_utc,
  cast(null as date) as date,
  cast(null as varchar) as session_id,
  cast(null as varchar) as visitor_id,
  cast(null as varchar) as pages_visited,
  cast(null as bigint) as event_count,
  cast(null as bigint) as error_count,
  cast(null as bigint) as total_runtime_ms,
  cast(null as varchar) as app_version,
  cast(null as varchar) as last_page,
  cast(null as varchar) as page_slug,
  cast(null as timestamp) as started_at,
  cast(null as timestamp) as ended_at,
  cast(null as timestamp) as snapshot_at,
  cast(null as varchar) as source_file,
  cast(null as timestamp) as ingested_at,
  cast(null as date) as ingestion_date
where false
{% else %}
with source_sessions as (
  select
    cast(ts_utc as timestamp) as ts_utc,
    cast(date as date) as date,
    session_id,
    {% if 'visitor_id' in session_cols %}
    visitor_id,
    {% else %}
    cast(null as varchar) as visitor_id,
    {% endif %}
    pages_visited,
    cast(event_count as bigint) as event_count,
    cast(error_count as bigint) as error_count,
    cast(total_runtime_ms as bigint) as total_runtime_ms,
    app_version,
    last_page,
    {% if 'page_slug' in session_cols %}
    page_slug,
    {% else %}
    cast(null as varchar) as page_slug,
    {% endif %}
    {% if 'started_at' in session_cols %}
    cast(started_at as timestamp) as started_at,
    {% else %}
    cast(null as timestamp) as started_at,
    {% endif %}
    {% if 'ended_at' in session_cols %}
    cast(ended_at as timestamp) as ended_at,
    {% else %}
    cast(null as timestamp) as ended_at,
    {% endif %}
    source_file,
    cast(ingested_at as timestamp) as ingested_at
  from {{ source('raw', 'website_sessions') }}
),
normalized as (
  select
    ts_utc,
    coalesce(date, cast(ts_utc as date)) as date,
    session_id,
    visitor_id,
    pages_visited,
    event_count,
    error_count,
    total_runtime_ms,
    app_version,
    last_page,
    coalesce(
      nullif(trim(page_slug), ''),
      case
        when nullif(trim(last_page), '') is null then null
        else lower(
          regexp_replace(
            regexp_replace(
              regexp_replace(trim(last_page), '^.*/', ''),
              '^\\d+_',
              ''
            ),
            '\\.py$',
            ''
          )
        )
      end
    ) as page_slug,
    coalesce(started_at, ts_utc) as started_at,
    coalesce(ended_at, ts_utc) as ended_at,
    ts_utc as snapshot_at,
    source_file,
    ingested_at,
    cast(ingested_at as date) as ingestion_date
  from source_sessions
),
ranked as (
  select
    *,
    row_number() over (
      partition by coalesce(nullif(trim(session_id), ''), '__missing_session__'), snapshot_at
      order by ingested_at desc nulls last, source_file desc
    ) as dedupe_rank
  from normalized
)
select
  ts_utc,
  date,
  session_id,
  visitor_id,
  pages_visited,
  event_count,
  error_count,
  total_runtime_ms,
  app_version,
  last_page,
  page_slug,
  started_at,
  ended_at,
  snapshot_at,
  source_file,
  ingested_at,
  ingestion_date
from ranked
where dedupe_rank = 1
{% endif %}
