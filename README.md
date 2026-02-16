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
[app]
name = "DataBuilds.dev"

[links]
github = "https://github.com/youruser"
linkedin = "https://linkedin.com/in/youruser"
email = "you@example.com"

[logging]
level = "INFO"
```

Docker secrets: mount `.streamlit/secrets.toml` into the container or set env vars such as `GITHUB_URL` and `CONTACT_EMAIL` at runtime. Never bake secrets into the image.

## Telemetry Logging (DigitalOcean Spaces)
Telemetry is shipped to Spaces as compressed JSONL event logs and optional Parquet session rollups.

**Env vars**
- `LOGGING_ENABLED=true|false`
- `LOG_SINK=stdout|spaces|stdout+spaces`
- `LOG_FLUSH_EVENTS=25`
- `LOG_FLUSH_SECONDS=5`
- `LOG_SESSION_FLUSH_SECONDS=60`
- `APP_VERSION=dev`
- `SPACES_BUCKET=your-bucket`
- `SPACES_REGION=nyc3`
- `SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com`
- `SPACES_ACCESS_KEY_ID=...`
- `SPACES_SECRET_ACCESS_KEY=...`
- `SPACES_PREFIX=telemetry/`

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
Optional storage and analytics use DigitalOcean Spaces. More detail in `docs/PORTFOLIO.md`.

## Repo Map
- `app.py` - Streamlit entrypoint
- `app/` - shell config and shared UI
- `pages/` - multipage Streamlit routes
- `projects/` - project code and artifacts
- `shared/` - utilities and services
- `static/` - assets
- `docs/` - portfolio narrative

## Tests
Run: `poetry run pytest projects/bibclean/tests` and `python -m compileall app pages projects shared`.
