{% macro attach_r2_iceberg_if_needed() %}
  {% if target.name != "iceberg" %}
    {{ log("Skipping R2 Iceberg attach (target is not iceberg).", info=True) }}
    {{ return("select 1") }}
  {% endif %}

  {% set catalog_uri = env_var("R2_ICEBERG_CATALOG_URI", "") %}
  {% set warehouse = env_var("R2_ICEBERG_WAREHOUSE", "") %}
  {% set token = env_var("R2_ICEBERG_TOKEN", "") %}

  {% if not catalog_uri or not warehouse or not token %}
    {{ log("R2 Iceberg env vars missing; skipping attach for target iceberg.", info=True) }}
    {{ return("select 1") }}
  {% endif %}

  {% set safe_catalog_uri = catalog_uri | replace("'", "''") %}
  {% set safe_warehouse = warehouse | replace("'", "''") %}
  {% set safe_token = token | replace("'", "''") %}

  {% if execute %}
    {% do run_query("INSTALL httpfs") %}
    {% do run_query("LOAD httpfs") %}
    {% do run_query("INSTALL iceberg") %}
    {% do run_query("LOAD iceberg") %}
    {% do run_query("DROP SECRET IF EXISTS r2_iceberg_secret") %}
    {% do run_query("CREATE SECRET r2_iceberg_secret (TYPE iceberg, TOKEN '" ~ safe_token ~ "')") %}
    {% do run_query("DETACH DATABASE IF EXISTS r2_iceberg") %}
    {% do run_query("ATTACH '" ~ safe_warehouse ~ "' AS r2_iceberg (TYPE iceberg, ENDPOINT '" ~ safe_catalog_uri ~ "', SECRET r2_iceberg_secret)") %}
    {{ log("Attached R2 Iceberg catalog as r2_iceberg.", info=True) }}
  {% endif %}

  {{ return("select 1") }}
{% endmacro %}

{% macro debug_attached_catalogs() %}
  {% set query = "select * from duckdb_databases()" %}
  {% if execute %}
    {% set results = run_query(query) %}
    {% if results %}
      {{ log(results.table | string, info=True) }}
    {% endif %}
  {% endif %}
  {{ return(query) }}
{% endmacro %}
