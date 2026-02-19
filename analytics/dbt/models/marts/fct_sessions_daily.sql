{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

select
  d.date,
  coalesce(s.active_sessions_from_snapshots, e.active_sessions_from_events, 0) as sessions,
  coalesce(s.active_sessions_from_snapshots, 0) as active_sessions_from_snapshots,
  coalesce(e.active_sessions_from_events, 0) as active_sessions_from_events,
  case
    when s.active_sessions_from_snapshots is not null then 'session_snapshots'
    when e.active_sessions_from_events is not null then 'events'
    else 'none'
  end as sessions_source
from (
  select distinct date
  from {{ ref('stg_website_events') }}
  union
  select distinct date
  from {{ ref('stg_website_sessions') }}
) d
left join (
  select
    date,
    count(distinct session_id) filter (
      where session_id is not null and nullif(trim(session_id), '') is not null
    ) as active_sessions_from_snapshots
  from {{ ref('stg_website_sessions') }}
  group by 1
) s on d.date = s.date
left join (
  select
    date,
    count(distinct session_id) filter (
      where session_id is not null and nullif(trim(session_id), '') is not null
    ) as active_sessions_from_events
  from {{ ref('stg_website_events') }}
  group by 1
) e on d.date = e.date
order by d.date
