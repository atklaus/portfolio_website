from __future__ import annotations

from typing import Callable

import streamlit as st


def render_transition_shell(page_title: str) -> tuple[st.container, Callable[[], None]]:
    spinner_slot = st.empty()

    spinner_slot.markdown(
        """
        <style>
        .ads-transition {
          display: inline-flex;
          align-items: center;
          gap: 0.6rem;
          padding: 0.35rem 0.75rem;
          border-radius: 999px;
          border: 1px solid rgba(155, 231, 216, 0.2);
          color: rgba(241, 251, 249, 0.9);
          background: rgba(255, 255, 255, 0.04);
          margin-bottom: 0.75rem;
        }
        .ads-transition-spinner {
          width: 14px;
          height: 14px;
          border-radius: 50%;
          border: 2px solid rgba(155, 231, 216, 0.25);
          border-top-color: rgba(155, 231, 216, 0.95);
          animation: ads-spin 0.8s linear infinite;
        }
        @keyframes ads-spin { to { transform: rotate(360deg); } }
        </style>
        <div class="ads-transition">
          <div class="ads-transition-spinner"></div>
          <div>Loading...</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    content_container = st.container()

    def _done() -> None:
        spinner_slot.empty()

    return content_container, _done
