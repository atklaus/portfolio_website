import re
from pathlib import Path

import streamlit as st

from .. import config as c
from lib.ops.memory import log_mem
from shared.seo import apply_page_meta
from shared.settings import email_href, get_settings
from shared.urls import app_path

BACKGROUND_COLOR = "white"
COLOR = "black"

# hide_streamlit_style = """
#                 <style>
#                 div[data-testid="stToolbar"] {
#                 visibility: hidden;
#                 height: 0%;
#                 position: fixed;
#                 }
#                 div[data-testid="stDecoration"] {
#                 visibility: hidden;
#                 height: 0%;
#                 position: fixed;
#                 }
#                 div[data-testid="stStatusWidget"] {
#                 visibility: hidden;
#                 height: 0%;
#                 position: fixed;
#                 }
#                 #MainMenu {
#                 visibility: hidden;
#                 height: 0%;
#                 }
#                 header {
#                 visibility: hidden;
#                 height: 0%;
#                 }
#                 footer {
#                 visibility: hidden;
#                 height: 0%;
#                 }
#                 </style>
#                 """


def set_page_container_style(
    max_width: int = 1100,
    max_width_100_percent: bool = False,
    padding_top: float = 1,
    padding_right: int = 10,
    padding_left: int = 1,
    padding_bottom: float = 0.25,
    color: str = COLOR,
    background_color: str = BACKGROUND_COLOR,
    apply: bool = True,
):
    if max_width_100_percent:
        max_width_str = "max-width: 100%;"
    else:
        max_width_str = f"max-width: {max_width}px;"
    css = f"""
        <style>
        .appview-container .main .block-container{{
                padding-top: {padding_top}rem !important;
                padding-bottom: {padding_bottom}rem !important;
                padding-left: {padding_left}rem !important;
                padding-right: {padding_right}rem !important;
                {max_width_str}
                }}
        </style>
        """
    if apply:
        st.markdown(css, unsafe_allow_html=True)
    return css


def _standardize_name(name: str) -> str:
    return name.strip().lower().replace("_", " ")


@st.cache_data(show_spinner=False, max_entries=2)
def _page_index():
    repo_root = Path(__file__).resolve().parents[2]
    pages_dir = repo_root / "pages"
    index = {}
    if pages_dir.exists():
        for path in pages_dir.glob("*.py"):
            slug = re.sub(r"^\d+_", "", path.stem)
            index[_standardize_name(slug)] = f"pages/{path.name}"
    index["home"] = "pages/0_home.py"
    return index


def get_page_path(name: str) -> str:
    from shared.pages import get_pages

    settings = get_settings()
    base_path = settings.app_base_path
    target = _standardize_name(name)
    for page in get_pages():
        slug = _standardize_name(page.key)
        stem = Path(page.file).stem
        parts = stem.split("_", 1)
        file_slug = _standardize_name(parts[1] if len(parts) > 1 and parts[0].isdigit() else stem)
        if slug == target or file_slug == target:
            if page.key == "home":
                return app_path("/", base_path)
            return app_path(f"/{page.url_path}", base_path)
    return app_path("/", base_path)


def render_sidebar_nav(page_name: str):
    with st.sidebar:
        settings = get_settings()
        base_path = settings.app_base_path
        github_profile_url = settings.github_url
        linkedin_profile_url = settings.linkedin_url
        email_address = email_href(settings.contact_email)

        try:
            section = st.query_params.get("section")
        except Exception:
            section = None
        if isinstance(section, list):
            section = section[0]
        if not section:
            section = "home"

        nav_items = [
            ("Home", "home"),
            ("Contact", "contact"),
        ]

        nav_links = []
        for label, anchor in nav_items:
            href = f"{app_path('/', base_path)}?section={anchor}#{anchor}"
            active = " active" if section == anchor else ""
            nav_links.append(
                f'<a class="ads-nav-item{active}" href="{href}" target="_self" rel="noopener">{label}</a>'
            )

        sidebar_html = f"""
<style>
.ads-sidebar {{
  padding-top: 0.5rem;
}}
.ads-sidebar h4 {{
  margin: 0 0 0.6rem 0;
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(241, 251, 249, 0.65);
}}
.ads-nav-list {{
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}}
.ads-nav-item {{
  padding: 0.45rem 0.65rem;
  border-radius: 10px;
  text-decoration: none;
  color: rgba(241, 251, 249, 0.85);
  font-size: 0.9rem;
  border: 1px solid transparent;
}}
.ads-nav-item:hover {{
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.06);
}}
.ads-nav-item.active {{
  background: rgba(155, 231, 216, 0.08);
  border-color: rgba(155, 231, 216, 0.2);
  color: rgba(241, 251, 249, 0.95);
}}
.ads-sidebar-links {{
  margin-top: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}}
.ads-sidebar-links a {{
  text-decoration: none;
  color: rgba(178, 200, 195, 0.9);
  font-size: 0.85rem;
}}
</style>
<div class="ads-sidebar">
  <h4>Sections</h4>
  <div class="ads-nav-list">
    {''.join(nav_links)}
  </div>
  <div class="ads-sidebar-links">
    <h4>Quick links</h4>
    <a href="{github_profile_url}" target="_blank" rel="noopener">GitHub</a>
    <a href="{linkedin_profile_url}" target="_blank" rel="noopener">LinkedIn</a>
    <a href="{email_address}" target="_blank" rel="noopener">Email</a>
  </div>
</div>
"""
        st.markdown(sidebar_html, unsafe_allow_html=True)


def page_header(title, page_name, container_style=True):
    try:
        apply_page_meta(str(page_name))
    except Exception:
        pass
    render_sidebar_nav(page_name)
    settings = get_settings()
    if settings.safe_mode:
        st.warning("Safe mode is enabled. Heavy demos and admin queries are disabled.")
    log_mem(f"page_header:{page_name}")
    if container_style:
        set_page_container_style(
            max_width_100_percent=True,
            padding_top=1,
            padding_bottom=0.25,
            padding_left=1.25,
            padding_right=1.25,
            apply=True,
        )

    settings = get_settings()
    github_profile_url = settings.github_url
    linkedin_profile_url = settings.linkedin_url
    brand_name = settings.app_name
    home_href = app_path("/", settings.app_base_path)
    navbar_html = f"""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css">
    <div class="ads-nav">
      <div class="content-shell ads-nav-inner">
        <div class="ads-nav-brand">{brand_name}</div>
        <div class="ads-nav-actions">
          <a class="ads-icon-btn" href="{home_href}" target="_self" rel="noopener" aria-label="Home"><i class="fas fa-home"></i></a>
          <a class="ads-icon-btn" href="{github_profile_url}" target="_blank" rel="noopener" aria-label="GitHub"><i class="fas fa-code"></i></a>
          <a class="ads-icon-btn" href="{linkedin_profile_url}" target="_blank" rel="noopener" aria-label="LinkedIn"><i class="fab fa-linkedin"></i></a>
        </div>
      </div>
    </div>
    """

    st.markdown(navbar_html, unsafe_allow_html=True)
