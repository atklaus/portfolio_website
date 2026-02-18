{% set sessions_rel = adapter.get_relation(database='r2_iceberg', schema='raw', identifier='website_sessions') %}

{% if sessions_rel %}
select
  date,
  count(distinct session_id) as sessions
from {{ ref('stg_website_sessions') }}
group by date
order by date
{% else %}
select
  date,
  count(distinct session_id) as sessions
from {{ ref('stg_website_events') }}
group by date
order by date
{% endif %}
