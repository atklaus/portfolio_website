{% set sessions_rel = adapter.get_relation(database='r2_iceberg', schema='raw', identifier='website_sessions') %}

{% if sessions_rel %}
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
{% else %}
select
  cast(null as timestamp) as ts_utc,
  cast(null as date) as date,
  cast(null as varchar) as session_id,
  cast(null as varchar) as pages_visited,
  cast(null as bigint) as event_count,
  cast(null as bigint) as error_count,
  cast(null as bigint) as total_runtime_ms,
  cast(null as varchar) as app_version,
  cast(null as varchar) as last_page,
  cast(null as varchar) as source_file,
  cast(null as timestamp) as ingested_at
where false
{% endif %}
