{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  database="r2_iceberg",
  schema="analytics"
) }}

select
  date,
  count(*) as pageviews
from {{ ref('stg_website_events') }}
where event_name = 'page_view'
group by date
order by date
