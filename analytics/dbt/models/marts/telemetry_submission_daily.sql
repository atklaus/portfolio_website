{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

select
  cast(submitted_at as date) as date,
  page_slug,
  count(*) as submissions_count,
  count(distinct visitor_id) filter (
    where visitor_id is not null and nullif(trim(visitor_id), '') is not null
  ) as unique_visitors_count
from {{ ref('telemetry_submissions') }}
group by 1, 2
order by 1, 2
