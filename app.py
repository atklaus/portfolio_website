import streamlit as st
import streamlit.components.v1 as components

from lib.analytics import inject_ga4
from lib.errors.boundary import get_app_env, run_with_error_boundary
from lib.ops.memory import log_mem
from shared.pages import get_pages
from shared.seo import ensure_sitemap
from shared.logging.ops import configure_logging
from shared.settings import get_settings
from shared.telemetry.config import warn_if_unconfigured

settings = get_settings()
configure_logging(settings.logging_level)
warn_if_unconfigured()
log_mem("app_start")

st.set_page_config(
    page_title=settings.app_name,
    page_icon="static/images/favicon.ico",
    layout="wide",
    initial_sidebar_state="collapsed",
)
if get_app_env() == "prod":
    try:
        st.set_option("client.showErrorDetails", False)
    except Exception:
        pass


def _maybe_redirect_static() -> None:
    script = """
    <script>
      (function() {
        const path = window.location.pathname;
        if (path === '/robots.txt') { window.location.replace('/static/robots.txt'); }
        if (path === '/sitemap.xml') { window.location.replace('/static/sitemap.xml'); }
      })();
    </script>
    """
    try:
        components.html(script, height=0, width=0)
    except Exception:
        pass


def _render_app() -> None:
    _maybe_redirect_static()
    inject_ga4(settings.ga_measurement_id)
    ensure_sitemap()

    with st.sidebar:
        st.empty()

    pages = [
        st.Page(
            page.file,
            title=page.title,
            icon=page.icon,
            url_path=page.url_path,
            default=page.key == "home",
        )
        for page in get_pages()
        if page.include_in_nav
    ]
    nav = st.navigation(pages, position="hidden")
    nav.run()


run_with_error_boundary(_render_app, page_id="navigation", context={})
log_mem("app_after_nav")
