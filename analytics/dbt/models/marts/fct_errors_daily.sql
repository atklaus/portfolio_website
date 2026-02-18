{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

select
  date,
  count(*) as errors
from {{ ref('stg_website_events') }}
where event_name = 'error'
group by date
order by date
