{{ config(
  tags=["iceberg"],
  enabled=(target.name == "iceberg"),
  schema="analytics"
) }}

with submission_events as (
  select
    event_name,
    coalesce(submitted_at, occurred_at, ts) as submitted_at,
    page_slug,
    session_id,
    visitor_id,
    submission_id,
    submission_number_in_session,
    fields,
    tags,
    event_id,
    source_file,
    ingested_at,
    ingestion_date
  from {{ ref('stg_website_events') }}
  where event_name = 'submission'
),
normalized as (
  select
    event_name,
    cast(submitted_at as timestamp) as submitted_at,
    coalesce(nullif(trim(page_slug), ''), 'unknown') as page_slug,
    coalesce(nullif(trim(session_id), ''), 'unknown_session') as session_id,
    nullif(trim(visitor_id), '') as visitor_id,
    nullif(trim(submission_id), '') as submission_id,
    submission_number_in_session,
    fields,
    tags,
    event_id,
    source_file,
    ingested_at,
    ingestion_date,
    md5(coalesce(cast(fields as varchar), '')) as fields_hash
  from submission_events
),
dedupe as (
  select
    *,
    coalesce(
      submission_id,
      md5(
        concat_ws(
          '|',
          coalesce(session_id, ''),
          coalesce(page_slug, ''),
          coalesce(cast(submitted_at as varchar), ''),
          coalesce(fields_hash, '')
        )
      )
    ) as dedupe_key
  from normalized
),
ranked as (
  select
    *,
    row_number() over (
      partition by dedupe_key
      order by ingested_at desc nulls last, source_file desc, event_id desc
    ) as dedupe_rank
  from dedupe
)
select
  event_name,
  submitted_at,
  page_slug,
  session_id,
  visitor_id,
  submission_id,
  submission_number_in_session,
  fields,
  tags,
  event_id,
  source_file,
  ingested_at,
  ingestion_date,
  dedupe_key
from ranked
where dedupe_rank = 1
