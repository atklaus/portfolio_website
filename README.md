# DataBuilds.dev - Data Engineering Portfolio

DataBuilds.dev is my Streamlit portfolio for end-to-end data engineering work. Start at the app homepage to explore featured projects and their production-style pipelines.

## Featured

### Predicting WNBA Success
Predict WNBA success from NCAA stats with live scraping and a cached model.
- Data: live scrape from sports-reference.com
- ML: classification with feature scaling and imputation
- Engineering: offline fixture mode and cached artifacts
Links: `pages/2_wnba_success.py` (open in app) | `projects/wnba_success/README.md` (project details)

### Landscape Image Prediction
Classify landscapes from user uploads using a tiled CNN inference pipeline.
- Data: user-uploaded images
- ML: CNN inference with tile aggregation
- Engineering: model artifacts packaged in repo
Links: `pages/1_landscape_img.py` (open in app) | `projects/landscape_img/README.md` (project details)

### Bibliometrix Reference Cleaner
Clean and canonicalize Scopus or WoS references for bibliometrix/Biblioshiny.
- Data: Scopus CSV and WoS plaintext exports
- ML: fuzzy matching and clustering
- Engineering: deterministic normalization with tests
Links: `pages/8_bibliometrix_reference_cleaner.py` (open in app) | `projects/bibclean/README.md` (project details)

## Other fun projects
- Random Ellipses: Monte Carlo overlap estimator. `projects/ellipses/README.md`
- Game of Life: Conway simulation visualizer. `projects/game_of_life/README.md`
- Happy Prime: happy number and prime check. `projects/happy_prime/README.md`

## Quickstart
**Poetry**: `poetry install` then `poetry run streamlit run app.py`
**Docker**: `docker build -t databuilds .` then `docker run -p 8501:8501 --env-file .env databuilds`

## Secrets
Create a local secrets file and keep it out of version control.
1. Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml`.
2. Update the values for your environment.

Example:
```toml
GA_MEASUREMENT_ID = "G-XXXXXXXXXX"
LOG_SINK = "stdout+r2"
LOGGING_ENABLED = true

[app]
name = "DataBuilds.dev"
site_url = "https://databuilds.dev"

[links]
github = "https://github.com/youruser"
linkedin = "https://linkedin.com/in/youruser"
email = "you@example.com"

[logging]
level = "INFO"
```

Docker secrets: mount `.streamlit/secrets.toml` into the container or set env vars such as `GITHUB_URL` and `CONTACT_EMAIL` at runtime. Never bake secrets into the image.
See `.streamlit/secrets.example.toml` for the full R2/SPACES credential set.

## SEO + Analytics
GA4 is optional and only loads when `GA_MEASUREMENT_ID` is set in `.streamlit/secrets.toml` or the environment.

Pages and titles are centralized in `shared/pages.py`, and the sitemap is generated from that registry on startup.

**Search Console setup**
1. Verify the domain in Google Search Console using the TXT record they provide.
2. Add the TXT record in Cloudflare DNS (Registrar/DNS).
3. Submit the sitemap: `https://databuilds.dev/sitemap.xml`.

**Robots + sitemap**
Static files live in `static/robots.txt` and `static/sitemap.xml` and are served at `/static/...`.
If root access does not resolve, add a Cloudflare Transform Rule:
- Rewrite `/robots.txt` to `/static/robots.txt`
- Rewrite `/sitemap.xml` to `/static/sitemap.xml`

## Fly.io Deployments
Deployments run on every push to `master` via GitHub Actions.
1. Create a Fly deploy token: `fly tokens create deploy -x 999999h`
2. Add the token as a GitHub repo secret: `FLY_API_TOKEN`
3. Push to `master` to trigger `fly deploy --remote-only`

## Storage + Telemetry (R2 preferred)
Object storage is S3-compatible. Cloudflare R2 is preferred, with Spaces/S3 as a fallback. The same config is used for telemetry and project storage.

**Project storage prefixes**
- `datasets/<project>/<name>/<version>/...`
- `artifacts/<project>/<name>/<run_id>/...`
- `models/<project>/<name>/<version>/...`
- `embeddings/<project>/<name>/<version>/...`
- `images/<project>/<name>/...`

**Telemetry prefixes**
- `telemetry/events/date=YYYY-MM-DD/events_<session_id>_<time>_<rand>.jsonl.gz`
- `telemetry/sessions/date=YYYY-MM-DD/sessions_<session_id>.parquet`

**Ops prefixes**
- `ops/logs/date=YYYY-MM-DD/instance=<id>/logs_<time>_<rand>.ndjson.gz`
- `ops/sessions/date=YYYY-MM-DD/session_<session_id>.json.gz`

**Retention recommendations (Cloudflare lifecycle rules)**
- `ops/logs`: 7–30d
- `telemetry/events`: 30–90d (depending on volume)
- `telemetry/sessions`: 90–365d
- `datasets/models/artifacts/embeddings/images`: indefinite

## Telemetry Logging (R2 preferred)
Telemetry is shipped to object storage as compressed JSONL event logs and optional Parquet session rollups. `LOG_SINK` also controls ops log shipping to `ops/logs`.

**Env vars**
- `LOGGING_ENABLED=true|false`
- `LOG_SINK=stdout|spaces|stdout+spaces` (aliases: `r2`, `s3`; example: `stdout+r2`)
- `LOG_FLUSH_EVENTS=25`
- `LOG_FLUSH_SECONDS=5`
- `LOG_SESSION_FLUSH_SECONDS=60`
- `APP_VERSION=dev`
- `R2_BUCKET=your-bucket`
- `R2_REGION=auto`
- `R2_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com`
- `R2_ACCESS_KEY_ID=...`
- `R2_SECRET_ACCESS_KEY=...`
- Legacy fallback:
- `SPACES_BUCKET=your-bucket`
- `SPACES_REGION=nyc3`
- `SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com`
- `SPACES_ACCESS_KEY_ID=...`
- `SPACES_SECRET_ACCESS_KEY=...`

**DuckDB queries**
```sql
SELECT COUNT(*)
FROM read_json_auto('s3://your-bucket/telemetry/events/date=*/events_*.jsonl.gz');

SELECT COUNT(*)
FROM read_parquet('s3://your-bucket/telemetry/sessions/date=*/sessions_*.parquet');
```

**Admin page**
Open `pages/9_telemetry_admin.py` to view sessions, page views, and errors using DuckDB.

## Architecture (High Level)
User -> Streamlit UI (`app.py`, `pages/*`) -> project modules (`projects/*`) -> data sources and model artifacts.
Optional storage and analytics use S3-compatible object storage (Cloudflare R2). More detail in `docs/PORTFOLIO.md`.

## Repo Map
- `app.py` - Streamlit entrypoint
- `app/` - shell config and shared UI
- `pages/` - multipage Streamlit routes
- `projects/` - project code and artifacts
- `shared/` - utilities and services
- `shared/pages.py` - page registry for navigation and sitemap
- `shared/seo.py` - sitemap generation and meta helpers
- `static/` - assets
- `docs/` - portfolio narrative

## Tests
Run: `poetry run pytest projects/bibclean/tests` and `python -m compileall app pages projects shared`.
