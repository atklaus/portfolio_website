select
  id,
  generated_at
from {{ ref('stg_example') }}
