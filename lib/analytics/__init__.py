import streamlit.components.v1 as components

from .marts import load_latest_manifest, read_latest_parquet_df


def inject_ga4(measurement_id: str) -> None:
    if not measurement_id:
        return
    snippet = f"""
    <script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{measurement_id}', {{ 'anonymize_ip': true }});
    </script>
    """
    try:
        components.html(snippet, height=0, width=0)
    except Exception:
        # Never allow analytics to break the app.
        pass

__all__ = ["load_latest_manifest", "read_latest_parquet_df", "inject_ga4"]
