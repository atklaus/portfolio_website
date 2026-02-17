from pathlib import Path

import streamlit as st

_BASE_CSS_PATH = Path(__file__).with_name("base.css")
_BASE_CSS_FALLBACK = ""


@st.cache_data(show_spinner=False)
def _load_base_css() -> str:
    try:
        return _BASE_CSS_PATH.read_text()
    except Exception:
        return _BASE_CSS_FALLBACK


def inject_base_css() -> None:
    css = _load_base_css()
    if not css:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
