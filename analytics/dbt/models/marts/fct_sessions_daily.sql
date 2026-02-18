{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

select
  date,
  count(distinct session_id) as sessions
from {{ ref('stg_website_events') }}
group by date
order by date