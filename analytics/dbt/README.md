# dbt DuckDB Analytics

This dbt project can run locally with no R2/Iceberg secrets. Iceberg models
only run when the `iceberg` target is selected.

Quick start (local, no secrets required):

```bash
cd analytics/dbt
dbt build --profiles-dir . --target local --exclude tag:iceberg
```

CI/Iceberg run (requires R2/Iceberg env vars):

```bash
cd analytics/dbt
dbt build --profiles-dir . --target iceberg
```
