{{ config(
  tags=["iceberg", "debug"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

with events_ranked as (
  select
    'website_events' as dataset,
    source_file,
    count(*) as row_count,
    max(occurred_at) as max_occurred_at,
    max(ingested_at) as max_ingested_at,
    row_number() over (
      order by max(ingested_at) desc nulls last, source_file desc
    ) as rn
  from {{ ref('stg_website_events') }}
  where source_file is not null and nullif(trim(source_file), '') is not null
  group by 1, 2
),
sessions_ranked as (
  select
    'website_sessions' as dataset,
    source_file,
    count(*) as row_count,
    max(snapshot_at) as max_occurred_at,
    max(ingested_at) as max_ingested_at,
    row_number() over (
      order by max(ingested_at) desc nulls last, source_file desc
    ) as rn
  from {{ ref('stg_website_sessions') }}
  where source_file is not null and nullif(trim(source_file), '') is not null
  group by 1, 2
),
unioned as (
  select dataset, source_file, row_count, max_occurred_at, max_ingested_at, rn
  from events_ranked
  where rn <= 20
  union all
  select dataset, source_file, row_count, max_occurred_at, max_ingested_at, rn
  from sessions_ranked
  where rn <= 20
)
select
  dataset,
  source_file,
  row_count,
  max_occurred_at,
  max_ingested_at
from unioned
order by dataset, max_ingested_at desc nulls last, source_file desc
