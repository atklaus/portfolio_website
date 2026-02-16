from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class AppSettings:
    app_name: str
    github_url: str
    linkedin_url: str
    contact_email: str
    logging_level: str


def _get_secret(section: str, key: str, default: str) -> str:
    try:
        section_val = st.secrets.get(section, {})
        if isinstance(section_val, dict):
            return section_val.get(key, default) or default
    except Exception:
        pass
    return default


def _get_env(key: str, default: str) -> str:
    value = os.environ.get(key)
    return value if value else default


def get_settings() -> AppSettings:
    app_name = _get_secret("app", "name", _get_env("APP_NAME", "DataBuilds.dev"))
    github_url = _get_secret("links", "github", _get_env("GITHUB_URL", "https://github.com/atklaus"))
    linkedin_url = _get_secret("links", "linkedin", _get_env("LINKEDIN_URL", "https://linkedin.com/in/adam-klaus"))
    contact_email = _get_secret("links", "email", _get_env("CONTACT_EMAIL", "atk14219@gmail.com"))
    logging_level = _get_secret("logging", "level", _get_env("LOG_LEVEL", "INFO"))
    return AppSettings(
        app_name=app_name,
        github_url=github_url,
        linkedin_url=linkedin_url,
        contact_email=contact_email,
        logging_level=logging_level,
    )


def email_href(email: str) -> str:
    if email.startswith("mailto:"):
        return email
    return f"mailto:{email}"
