{% macro attach_r2_iceberg_if_needed() %}
  {{ log("attach_r2_iceberg_if_needed invoked, target=" ~ target.name, info=True) }}

  {% if target.name != "iceberg" %}
    {{ log("Skipping R2 Iceberg attach (target is not iceberg).", info=True) }}
    {{ return("select 1") }}
  {% endif %}

  {% set catalog_uri = env_var("R2_ICEBERG_CATALOG_URI", "") %}
  {% set warehouse = env_var("R2_ICEBERG_WAREHOUSE", "") %}
  {% set token = env_var("R2_ICEBERG_TOKEN", "") %}

  {% set has_catalog_uri = (catalog_uri | length) > 0 %}
  {% set has_warehouse = (warehouse | length) > 0 %}
  {% set has_token = (token | length) > 0 %}

  {{ log("R2 Iceberg env present? catalog_uri=" ~ has_catalog_uri ~ " warehouse=" ~ has_warehouse ~ " token=" ~ has_token, info=True) }}

  {% if not has_catalog_uri or not has_warehouse or not has_token %}
    {{ log("R2 Iceberg env vars missing; skipping attach for target iceberg.", info=True) }}
    {{ return("select 1") }}
  {% endif %}

  {% set safe_catalog_uri = catalog_uri | replace("'", "''") %}
  {% set safe_warehouse = warehouse | replace("'", "''") %}
  {% set safe_token = token | replace("'", "''") %}

  {% if execute %}
    {% set existing = run_query("select 1 from duckdb_databases() where database_name = 'r2_iceberg' limit 1") %}
    {% if existing and existing.rows and (existing.rows | length) > 0 %}
      {{ log("r2_iceberg already attached on this connection; skipping attach.", info=True) }}
      {{ return("select 1") }}
    {% endif %}

    {% do run_query("INSTALL httpfs") %}
    {% do run_query("LOAD httpfs") %}

    {# Iceberg: force a modern extension bundle (CI commonly lags otherwise) #}
    {% do run_query("INSTALL iceberg") %}
    {% do run_query("LOAD iceberg") %}

    {# Debug: confirm extension is actually loaded #}
    {% set ext = run_query("select extension_name, installed, loaded from duckdb_extensions() where extension_name in ('iceberg','httpfs')") %}
    {% if ext %}
      {{ log(ext.table | string, info=True) }}
    {% endif %}

    {# Secret provider is registered by the iceberg extension; this is where you were failing #}
    {% do run_query("CREATE OR REPLACE SECRET r2_iceberg_secret (TYPE iceberg, TOKEN '" ~ safe_token ~ "')") %}

    {% do run_query("DETACH DATABASE IF EXISTS r2_iceberg") %}
    {% do run_query("ATTACH '" ~ safe_warehouse ~ "' AS r2_iceberg (TYPE iceberg, ENDPOINT '" ~ safe_catalog_uri ~ "', SECRET r2_iceberg_secret)") %}

    {% set dbs = run_query("select database_name from duckdb_databases()") %}
    {% if dbs %}
      {{ log(dbs.table | string, info=True) }}
    {% endif %}
  {% endif %}

  {{ return("select 1") }}
{% endmacro %}
