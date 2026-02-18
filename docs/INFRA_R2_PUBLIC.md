# R2 Public Bucket for dbt Docs

## Overview

This repo serves public dbt docs from a dedicated Cloudflare R2 bucket through a
Cloudflare Worker. The Worker applies iframe-friendly headers and cache control
rules so the docs can be embedded in the Streamlit app at https://databuilds.dev.

## Bucket and URL

- R2 bucket name: `databuilds-public`
- Public URL pattern: `https://public.databuilds.dev/<path>`
- dbt docs entrypoint: `/dbt_docs/latest/index.html`

Example:

`https://public.databuilds.dev/dbt_docs/latest/index.html`

## Required Response Headers

The Worker enforces the following headers on all responses:

- `Content-Security-Policy: frame-ancestors https://databuilds.dev http://localhost:8501`
- No `X-Frame-Options` header (explicitly removed if present)
- Cache-Control rule: `index.html` and `*.json` -> `no-cache`
- Cache-Control rule: `/assets/*` -> `public, max-age=31536000, immutable`

## App Configuration

The Streamlit app reads these environment variables (or `st.secrets`) for the
dbt/Elementary embeds:

- `DBT_DOCS_BASE_URL` (default: `https://public.databuilds.dev/dbt_docs/latest`)
- `ELEMENTARY_BASE_URL` (optional, for the Quality tab)

## Worker Configuration

Worker source and config live in:

- `workers/public_r2/src/index.js`
- `workers/public_r2/wrangler.toml`

The Worker routes `public.databuilds.dev/*` and reads objects from the
`databuilds-public` R2 bucket via the `PUBLIC_BUCKET` binding.

## CI Uploads

The GitHub Actions workflow `.github/workflows/dbt_docs.yaml`:

- Runs `dbt docs generate` in `analytics/dbt`.
- Uploads `analytics/dbt/target/` to R2 under `dbt_docs/<git_sha>/...` and
  `dbt_docs/latest/...`.

Cache headers are enforced at the Worker layer to ensure consistent behavior
regardless of upload metadata.

## Security Notes

- Only `databuilds-public` is intended to be public.
- All other R2 buckets should remain private and should not be mapped to a
  public Worker route.
