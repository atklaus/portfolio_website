# dbt DuckDB Analytics

This dbt project builds analytics models into a local DuckDB file at
`analytics/artifacts/warehouse.duckdb` (see `profiles.yml.example`).

In CI, the analytics workflow runs dbt against that local DuckDB file and then
exports marts to Parquet, uploading them to R2 via
`analytics/pipelines/publish_dbt_marts.py`.

Quick start (local):

```bash
cp analytics/dbt/profiles.yml.example analytics/dbt/profiles.yml
cd analytics/dbt
poetry install --with analytics
poetry run dbt run
poetry run dbt test
```

Publishing marts (local, requires R2 credentials in env):

```bash
poetry run python analytics/pipelines/publish_dbt_marts.py \
  --project databuilds \
  --models mart_example
```
