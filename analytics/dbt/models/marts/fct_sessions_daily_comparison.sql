{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

with sessions_from_events as (
  select
    date,
    count(distinct session_id) filter (
      where session_id is not null and nullif(trim(session_id), '') is not null
    ) as active_sessions_from_events
  from {{ ref('stg_website_events') }}
  group by 1
),
sessions_from_snapshots as (
  select
    date,
    count(distinct session_id) filter (
      where session_id is not null and nullif(trim(session_id), '') is not null
    ) as active_sessions_from_snapshots
  from {{ ref('stg_website_sessions') }}
  group by 1
)
select
  coalesce(s.date, e.date) as date,
  coalesce(s.active_sessions_from_snapshots, 0) as active_sessions_from_snapshots,
  coalesce(e.active_sessions_from_events, 0) as active_sessions_from_events,
  coalesce(s.active_sessions_from_snapshots, 0) - coalesce(e.active_sessions_from_events, 0) as sessions_delta,
  case
    when coalesce(e.active_sessions_from_events, 0) = 0 then null
    else round(
      (
        (coalesce(s.active_sessions_from_snapshots, 0) - coalesce(e.active_sessions_from_events, 0))
        * 100.0
      ) / coalesce(e.active_sessions_from_events, 0),
      2
    )
  end as pct_delta_vs_events
from sessions_from_snapshots s
full outer join sessions_from_events e
  on s.date = e.date
order by 1
