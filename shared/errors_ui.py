from __future__ import annotations

import streamlit as st

from shared.settings import email_href, get_settings


def render_error_banner(trace_id: str) -> None:
    st.error("We hit an error\n\nIssue has been logged and will be resolved.")
    st.caption(f"Reference: {trace_id}")
    st.code(trace_id)

    if st.button("Reload page", key=f"error-reload-{trace_id}"):
        st.rerun()

    try:
        email = get_settings().contact_email
    except Exception:
        email = ""
    if email:
        st.markdown(f"[Report]({email_href(email)})", unsafe_allow_html=True)
