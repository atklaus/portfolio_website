import streamlit as st
import streamlit.components.v1 as components

from lib.analytics import inject_ga4
from shared.pages import get_pages
from shared.seo import ensure_sitemap
from shared.logging.ops import configure_logging
from shared.settings import get_settings
from shared.telemetry.config import warn_if_unconfigured

settings = get_settings()
configure_logging(settings.logging_level)
warn_if_unconfigured()

st.set_page_config(
    page_title=settings.app_name,
    page_icon="static/images/favicon.ico",
    layout="wide",
    initial_sidebar_state="collapsed",
)


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


_maybe_redirect_static()
inject_ga4(settings.ga_measurement_id)
ensure_sitemap()

with st.sidebar:
    st.empty()

PAGES = [
    st.Page(page.file, title=page.title, icon=page.icon, default=page.key == "home")
    for page in get_pages()
    if page.include_in_nav
]

nav = st.navigation(PAGES, position="hidden")
nav.run()
