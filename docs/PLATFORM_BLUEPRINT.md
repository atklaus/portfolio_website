# Streamlit Platform Blueprint (databuilds.dev)

## Purpose
Portable, implementation-ready blueprint of the reusable Streamlit platform architecture in this repo, with clear boundaries between framework/platform code and project/page-specific code.

## 1) Repo Map

### Top-level directories

| Path | Role | Platform vs project |
|---|---|---|
| `.github/workflows/` | CI, deploy, analytics/dbt pipelines | Platform (ops) |
| `.streamlit/` | Streamlit runtime config (`enableStaticServing`, theme defaults) | Platform |
| `analytics/` | dbt project, GX config, ETL/export scripts | Platform (data stack) |
| `app/` | Shared UI layer (header, cards, global CSS/theme), module catalog | Platform |
| `data/` | Local runtime logs/cache artifacts | Environment-specific |
| `docs/` | Infra/SEO/telemetry documentation | Platform docs |
| `lib/` | Reusable infra libraries (SEO injection, storage, DuckDB/Iceberg, errors, telemetry schema) | Platform |
| `pages/` | Streamlit pages discovered at runtime | Mostly project/page-specific (with platform hooks) |
| `projects/` | Domain/project logic and model assets | Project-specific |
| `scripts/` | Operational scripts (SEO publish, Iceberg load, validations) | Platform (ops) |
| `shared/` | Cross-cutting platform modules (settings, telemetry runtime, routing metadata, SEO, logging) | Platform |
| `static/` | Static assets + SEO files (`robots.txt`, `sitemap.xml`) | Mixed (platform + branding) |
| `workers/` | Cloudflare Worker to serve public docs/SEO files from R2 | Platform (deployment edge) |
| `layout/` | Legacy/unused package stub (no active source files) | Ignore for port |
| `tests/` | Tests for storage/SEO/telemetry/error boundaries | Platform quality |

### Entrypoint and navigation

- Entrypoint: `app.py`.
- `st.set_page_config(...)` is called once with app name from settings.
- Navigation is built with `st.Page(...)` + `st.navigation(...)`:
  - Page list source: `shared.pages.get_pages()`.
  - `url_path` for each page comes from page metadata (`PageDef.url_path`).
  - Default page is key `home`.
  - `position="hidden"`; built-in nav is hidden in favor of custom UI.
- Runtime shell behavior in `app.py`:
  - Inject global CSS (`app.shared_ui.theme.inject_base_css`).
  - Inject GA4 snippet if configured (`lib.analytics.inject_ga4`).
  - Generate/update `static/sitemap.xml` on app start (`shared.seo.ensure_sitemap`).
  - JS redirect for `/robots.txt` and `/sitemap.xml` to `/static/*`.
  - Wrap render in global error boundary (`lib.errors.boundary.run_with_error_boundary`).

### Page discovery

- Discovery is dynamic, not static list.
- `shared/pages.py` scans `pages/*.py` and parses filenames:
  - Ordering via numeric prefix (`0_home.py`, `1_*`, ...).
  - Slug from filename stem without numeric prefix.
  - Metadata enrichment from `app/config.py:MOD_ACCESS`.
- URL slug source:
  - `PageDef.url_path` defaults to `key` (usually slug), overridable via `_OVERRIDES` in `shared/pages.py`.
- Visibility rules:
  - `enabled=False` in `MOD_ACCESS` removes page from nav and sitemap.
  - `hidden=True` in `MOD_ACCESS` is used by home-card rendering, not by nav builder directly.

### Shared UI components and wiring

- Global theme/CSS:
  - `app/shared_ui/base.css`
  - injected once in `app.py` by `app/shared_ui/theme.py`.
- Header/navbar/sidebar wrapper:
  - `app/layout/header.py` (`page_header`, `render_sidebar_nav`, `set_page_container_style`, `get_page_path`).
  - Most pages call `page_header(...)` at top.
- Card system for home/projects:
  - `app/ui/cards.py` (`ProjectCard`, `render_project_cards`).
  - Home page builds card list from `MOD_ACCESS`.
- Transition shell/spinner:
  - `shared/layout/transition.py`, used in `app.py` around `nav.run()`.

### Config patterns

- App/site settings (central): `shared/settings.py`.
  - Dataclass `AppSettings` loaded from `st.secrets` first, then env fallback.
  - Includes `APP_NAME`, `SITE_URL`, social links, GA ID, `APP_SAFE_MODE`, `LOG_LEVEL`.
- Page catalog + feature flags: `app/config.py` (`MOD_ACCESS`, `MOD_ADMIN_ENABLED`).
- Storage provider abstraction: `lib/storage/s3_compat.py`.
  - Provider precedence: `R2_*` -> `SPACES_*` -> `S3_*`.
- Telemetry config: `shared/telemetry/config.py`.
  - `LOGGING_ENABLED`, `LOG_SINK`, flush windows, buffer size, app version.
- Streamlit runtime config: `.streamlit/config.toml`.
  - `enableStaticServing = true` is required for `/static/*` serving.

### SEO plumbing

- Page-level social metadata:
  - `shared/seo.py:apply_page_meta(...)` called from `app/layout/header.py`.
  - `lib/seo.py:inject_social_meta(...)` injects OG/Twitter meta tags via JS into parent document.
- Sitemap generation:
  - `shared/seo.py:ensure_sitemap()` generates `static/sitemap.xml` from discovered pages.
  - Includes only pages with `include_in_nav` and `include_in_sitemap`.
- Robots:
  - `static/robots.txt` is static; includes sitemap URL.
- Publish/static hosting:
  - `scripts/publish_seo_static.py` uploads `robots.txt` and `sitemap.xml` to R2.
  - Cloudflare Worker serves `/robots.txt` and `/sitemap.xml` from public bucket.
- Validation:
  - `scripts/validate_sitemap.py` checks base URL, home URL presence, and slug formatting.

Note: There is no explicit `<link rel="canonical">` tag injection. Canonicalization is represented through sitemap URLs and `og:url` metadata.

### Analytics/telemetry integration points

- GA4 (optional):
  - `app.py` calls `inject_ga4(settings.ga_measurement_id)`.
  - No ID => no injection.
- Custom telemetry runtime:
  - Per-page instrumentation via `with shared.telemetry.page_guard(os.path.basename(__file__)):`.
  - Event logging (`log_event`) and error logging (`log_error`) buffered in session state.
  - Sinks in `shared/telemetry/sinks.py`: `stdout`, `local`, `r2/spaces/s3`.
  - Submission tracking via `track_submission(...)` (actively used in `pages/2_wnba_success.py`).
- Telemetry storage paths:
  - Raw events: `telemetry/events/date=.../events_*.jsonl.gz`.
  - Session snapshots: `telemetry/sessions/date=.../sessions_*.parquet`.
  - Parquet rollups: `telemetry/events_parquet/date=.../part-*.parquet`.
- Iceberg ingestion:
  - `scripts/load_telemetry_to_iceberg.py` loads parquet sources into `r2_iceberg.raw.*`.
- Admin analytics page:
  - `pages/9_telemetry.py` queries `r2_iceberg.analytics.*` through `shared/duckdb_client.py`.

### dbt + DuckDB integration patterns

- dbt project location: `analytics/dbt/`.
- Profile switching:
  - `profiles.yml` chooses `iceberg` target when `R2_ICEBERG_TOKEN` exists, else `local`.
  - Uses `DBT_DUCKDB_PATH` for local DuckDB artifact DB.
- Catalog attach macro:
  - `analytics/dbt/macros/r2_iceberg.sql` attaches Iceberg catalog at run start for iceberg target.
- Schema strategy:
  - `generate_schema_name.sql` prefixes schemas with `r2_iceberg.` on iceberg target.
- Runtime app db access:
  - `shared/duckdb_client.py` opens DuckDB file, attaches Iceberg catalog lazily, exposes `query_df`.
- Docs hosting + iframe embedding:
  - `pages/3_data_platform.py` fetches `manifest.json`/`catalog.json`/`run_results.json` from `DBT_DOCS_BASE_URL`.
  - Embeds dbt and GX docs with `streamlit.components.v1.iframe(...)`.
  - Defaults: `https://public.databuilds.dev/dbt_docs/latest` and `/gx/latest`.

### Deployment assumptions

- App runtime:
  - `Dockerfile` builds Poetry dependencies (`--only main`) and runs `streamlit run app.py`.
  - No dbt runtime in serving container by design.
- Hosting:
  - `fly.toml` runs Streamlit on Fly.io (`streamlit-portfolio` app name).
- Public static/docs edge serving:
  - Cloudflare Worker in `workers/public_r2/` routes:
    - `public.databuilds.dev/*`
    - `databuilds.dev/*`
  - Binds R2 bucket `databuilds-public`.
- CI/CD:
  - `.github/workflows/ci.yml`: tests + Fly deploy on `master` push.
  - `.github/workflows/analytics_pipeline.yml`: telemetry parquet build, Iceberg load, dbt build/docs, SEO publish, GX docs upload.
  - `.github/workflows/analytics.yaml` and `telemetry_iceberg_nightly.yaml` are additional scheduled jobs.

### Platform/framework vs project/page-specific

**Platform/framework:**
- App shell, routing, page discovery, settings/secrets, SEO/meta/sitemap, telemetry runtime/sinks, storage abstraction, DuckDB/Iceberg attach/query, deployment workflows, Worker serving layer.

**Project/page-specific:**
- `projects/*` business logic/models/assets.
- Most contents of `pages/*.py` (forms, domain logic, project text/branding).
- Brand assets and copy in `static/images`, home hero/footer text.
- `app/config.py:MOD_ACCESS` project catalog entries.

---

## 2) Portability Units

## Unit A: App Shell + Navigation
- Purpose: Single Streamlit entrypoint that centrally configures global behavior and routes pages.
- Files involved: `app.py`, `shared/pages.py`, `app/config.py`.
- Public interface: Add a page by creating `pages/N_slug.py` and optional `MOD_ACCESS` metadata entry.
- Dependencies: Streamlit 1.54+, page files, settings, header/page patterns.
- Safe to copy as-is: `app.py`, `shared/pages.py`.
- Must customize: `app/config.py` page catalog content, default app/site metadata values.

## Unit B: Settings + Secrets Adapter
- Purpose: One typed settings surface for app name, URLs, links, GA, safe mode, log level.
- Files involved: `shared/settings.py`.
- Public interface: `settings = get_settings()`; `email_href(...)`.
- Dependencies: `st.secrets`, environment variables.
- Safe to copy as-is: entire file.
- Must customize: default values (`DataBuilds.dev`, `databuilds.dev`, social/contact links).

## Unit C: Shared Layout/Header/UI Theme
- Purpose: Reusable UI shell so each page has consistent header/nav spacing and style.
- Files involved: `app/layout/header.py`, `app/shared_ui/base.css`, `app/shared_ui/theme.py`, `app/ui/cards.py`, `app/shared_ui/st_utils.py`.
- Public interface: `page_header(title, page_name)`, `render_project_cards(cards)`.
- Dependencies: Streamlit markdown/html rendering, Font Awesome CDN, `shared.pages`.
- Safe to copy as-is: base structure and helper functions.
- Must customize: brand name, links, section labels, CSS palette/fonts, home/footer copy.

## Unit D: SEO Layer
- Purpose: Inject social metadata and maintain sitemap/robots outputs.
- Files involved: `shared/seo.py`, `lib/seo.py`, `static/robots.txt`, `scripts/validate_sitemap.py`, `scripts/publish_seo_static.py`.
- Public interface: `apply_page_meta(page_name)` (called by header), `ensure_sitemap()` (called in app shell).
- Dependencies: page registry, settings site URL, R2 credentials for publish script.
- Safe to copy as-is: SEO python modules and publish/validate scripts.
- Must customize: domain URLs in defaults and `robots.txt`, social image path, sitemap base URL expectations.

## Unit E: Error Boundary + Error UI
- Purpose: Prevent hard crashes and provide user-friendly trace IDs with optional detail in non-prod.
- Files involved: `lib/errors/boundary.py`, `lib/errors/logging.py`, `shared/errors_ui.py`.
- Public interface: `run_with_error_boundary(fn, page_id, context)`.
- Dependencies: telemetry/event logging and app env (`APP_ENV`).
- Safe to copy as-is: entire unit.
- Must customize: support email/contact behavior if desired.

## Unit F: Telemetry Runtime + Sinks (Optional)
- Purpose: Instrument page views/errors/submissions and persist telemetry to stdout/local/object storage.
- Files involved: `shared/telemetry/*`, `lib/telemetry/privacy.py`, `lib/telemetry/schema.py`, `lib/storage/paths.py`, `shared/logging/ops.py`.
- Public interface:
  - Per page: `with page_guard(os.path.basename(__file__)):`
  - Optional submission: `track_submission(page_id, form_id, inputs, tags)`
- Dependencies: Streamlit session state, storage config, optional DuckDB/pandas for session parquet sink.
- Safe to copy as-is: module implementations.
- Must customize: `TELEMETRY_SUBMISSION_TRACKING` mapping and allowed/redacted fields per page.

## Unit G: Storage Abstraction (Optional but recommended)
- Purpose: Provider-agnostic object storage access (R2/Spaces/S3) and key conventions.
- Files involved: `lib/storage/s3_compat.py`, `lib/storage/io.py`, `lib/storage/paths.py`.
- Public interface: `get_storage_config()`, `get_client()`, `put_bytes()`, `put_file()`, key helper functions.
- Dependencies: boto3/botocore.
- Safe to copy as-is: full directory.
- Must customize: env/secrets in deployment environments only.

## Unit H: DuckDB + Iceberg Query Adapter (Optional)
- Purpose: Query analytics tables from Streamlit with automatic Iceberg attachment.
- Files involved: `shared/duckdb_client.py`, `lib/duckdb_iceberg.py`.
- Public interface: `query_df(sql, params)`, `ensure_r2_iceberg_attached(conn)`, `connect_iceberg()`.
- Dependencies: DuckDB `httpfs` + `iceberg` extensions and R2/Iceberg credentials.
- Safe to copy as-is: files.
- Must customize: env variable provisioning and warehouse/catalog values.

## Unit I: dbt/GX Docs + Data Platform Page (Optional)
- Purpose: Surface lineage/ops in-app and embed docs from public object storage.
- Files involved: `pages/3_data_platform.py`, `analytics/dbt/*`, `scripts/run_gx.py`, `workers/public_r2/*`, `docs/INFRA_R2_PUBLIC.md`.
- Public interface: page loads `manifest.json`, `catalog.json`, `run_results.json` from `DBT_DOCS_BASE_URL`; embeds iframe.
- Dependencies: dbt docs artifacts in public bucket; Worker CSP `frame-ancestors` must allow app domain.
- Safe to copy as-is: dbt project structure, worker template, docs page logic.
- Must customize: docs base URLs, worker routes/domains, bucket names, model/package naming.

## Unit J: CI/CD Pipeline (Optional)
- Purpose: Keep runtime app lean while running heavy analytics in scheduled jobs.
- Files involved: `.github/workflows/ci.yml`, `analytics_pipeline.yml`, `analytics.yaml`, `telemetry_iceberg_nightly.yaml`, `scripts/load_telemetry_to_iceberg.py`, `analytics/pipelines/*.py`.
- Public interface: GitHub Actions triggered by schedule/push/workflow_dispatch.
- Dependencies: repo secrets (`R2_*`, `R2_ICEBERG_*`, `FLY_API_TOKEN`), Poetry, dbt, awscli.
- Safe to copy as-is: workflow skeleton + script structure.
- Must customize: trigger branches/schedules, app name/deploy target, secret names if different.

---

## 3) Port Plan (Checklist)

### A) Minimal viable platform (routing + nav + shared layout)
1. Copy `app.py`, `shared/pages.py`, `shared/settings.py`, `app/layout/`, `app/shared_ui/`, `app/ui/cards.py`.
2. Create initial `pages/0_home.py` and at least one additional page file (`pages/1_x.py`).
3. Define `MOD_ACCESS` entries in `app/config.py` to map slugs to titles/icons/descriptions.
4. Ensure each page wraps body with `page_guard(...)` and calls `page_header(...)`.
5. Set `.streamlit/config.toml` with `enableStaticServing = true`.
6. Run `streamlit run app.py` and verify:
   - dynamic page discovery order,
   - correct `url_path` routing,
   - hidden built-in nav with custom header/sidebar.

### B) SEO layer
1. Copy `shared/seo.py`, `lib/seo.py`, `static/robots.txt`, `scripts/validate_sitemap.py`.
2. Confirm `ensure_sitemap()` is called from `app.py` and `apply_page_meta()` from `page_header()`.
3. Set `SITE_URL` and `SOCIAL_IMAGE_URL` (or secrets equivalents).
4. Update `robots.txt` `Sitemap:` line for new domain.
5. Run `python scripts/validate_sitemap.py`.

### C) Telemetry/analytics (optional)
1. Copy `shared/telemetry/`, `shared/logging/ops.py`, `lib/telemetry/`, `lib/storage/`.
2. Configure `LOG_SINK` (`stdout`, `local`, or `stdout+r2`) and `R2_*` if using object storage.
3. Add `track_submission(...)` only on explicit form submit events.
4. Define allowlisted fields/redaction in `shared/telemetry/config.py`.
5. Validate emitted keys and payload shape locally (`LOG_SINK=local`) before enabling R2.

### D) dbt docs + iframes (optional)
1. Copy `analytics/dbt/`, `pages/3_data_platform.py`, `scripts/run_gx.py`, Worker files under `workers/public_r2/`.
2. Set `DBT_DOCS_BASE_URL` and `GX_DOCS_BASE_URL` to public docs prefixes.
3. Run dbt build/docs in CI and upload artifacts to public bucket prefix (`dbt_docs/latest`, `gx/latest`).
4. Configure Worker routes and CSP `frame-ancestors` to allow new app domain.
5. Verify iframe loads from Streamlit page and open-in-new-tab links resolve.

### E) CI/CD notes (optional)
1. Copy workflow YAMLs from `.github/workflows/`.
2. Update trigger branches and schedule windows.
3. Set required secrets in GitHub: app deploy token + R2/Iceberg credentials.
4. Decide whether to keep all three analytics workflows or consolidate to one.
5. Keep runtime image lean (`Dockerfile` without analytics extras) and run heavy jobs in CI.

---

## Copy List (verbatim candidates)

### Core platform
- `app.py`
- `shared/pages.py`
- `shared/settings.py`
- `app/layout/`
- `app/shared_ui/`
- `app/ui/cards.py`
- `shared/layout/transition.py`
- `lib/errors/`
- `shared/errors_ui.py`
- `.streamlit/config.toml`

### SEO
- `shared/seo.py`
- `lib/seo.py`
- `static/robots.txt` (then edit domain)
- `scripts/validate_sitemap.py`
- `scripts/publish_seo_static.py`

### Telemetry/storage (optional)
- `shared/telemetry/`
- `shared/logging/ops.py`
- `lib/telemetry/`
- `lib/storage/`
- `scripts/load_telemetry_to_iceberg.py`
- `analytics/pipelines/build_events_parquet.py`

### Analytics/dbt/docs (optional)
- `analytics/dbt/`
- `pages/3_data_platform.py`
- `pages/9_telemetry.py`
- `shared/duckdb_client.py`
- `lib/duckdb_iceberg.py`
- `workers/public_r2/`
- `.github/workflows/analytics_pipeline.yml`

### Deployment
- `Dockerfile`
- `fly.toml`
- `.github/workflows/ci.yml`

---

## Variables to Replace

### Branding and domain
- `APP_NAME`
- `SITE_URL`
- `SOCIAL_IMAGE_URL`
- `GITHUB_URL`, `LINKEDIN_URL`, `CONTACT_EMAIL`
- Home page copy in `pages/0_home.py` and footer text.

### Navigation and page catalog
- `app/config.py:MOD_ACCESS` entries:
  - labels/icons/descriptions/tags/groups,
  - enabled flags,
  - slugs matching page filenames.
- Page filenames and numeric ordering in `pages/`.

### SEO/static routes
- `static/robots.txt` sitemap domain.
- `scripts/validate_sitemap.py` `BASE_URL`.

### Telemetry and storage
- `LOG_SINK`, `LOGGING_ENABLED`, flush/buffer env vars.
- `R2_*` / `SPACES_*` / `S3_*` credentials and bucket names.
- `TELEMETRY_SUBMISSION_TRACKING` page keys and field allowlists/redaction rules.

### dbt + docs hosting
- `DBT_DOCS_BASE_URL`, `GX_DOCS_BASE_URL`.
- `R2_ICEBERG_CATALOG_URI`, `R2_ICEBERG_WAREHOUSE`, `R2_ICEBERG_TOKEN`.
- Worker `routes` and `bucket_name` in `workers/public_r2/wrangler.toml`.
- Worker CSP `frame-ancestors` in `workers/public_r2/src/index.js`.

### Deployment
- `fly.toml` app name/process settings.
- GitHub workflow branch filters/schedules/secrets.

---

## Gotchas

1. `st.navigation(position="hidden")` means built-in nav UI is gone; if custom header/sidebar links are wrong, users can get stranded.
2. Page URL slugs are derived from filenames + config. Renaming `pages/N_slug.py` changes route behavior and sitemap URLs.
3. `MOD_ACCESS.hidden` does not automatically hide pages from `st.navigation`; only `enabled=False` currently suppresses nav/sitemap in `shared/pages.py`.
4. `ensure_sitemap()` writes `static/sitemap.xml` at runtime; failures are swallowed. In restricted filesystems this can silently no-op.
5. SEO meta tags are injected via JS (`components.html`) into parent document; strict CSP/embedding differences can break this silently.
6. Every rerun triggers page instrumentation (`page_guard`); expect high event volume on interactive pages.
7. Submission dedupe only covers a short window (`dedupe_window_seconds`), not permanent dedupe.
8. Iceberg attach requires DuckDB extension install/load (`httpfs`, `iceberg`); cold environments without extension access can fail attach.
9. Data Platform docs iframes require Worker CSP `frame-ancestors` to include the app origin; otherwise iframe appears blank/blocked.
10. CI currently has overlapping analytics workflows (`analytics_pipeline.yml`, `analytics.yaml`, `telemetry_iceberg_nightly.yaml`); avoid double-running jobs in the new repo unless intentional.
11. Legacy docs mention an `analytics_docs.yaml` workflow name, but actual file is `analytics_pipeline.yml`.
