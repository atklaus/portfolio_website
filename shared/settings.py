from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class AppSettings:
    app_name: str
    site_url: str
    app_base_path: str
    social_image_url: str
    github_url: str
    linkedin_url: str
    contact_email: str
    logging_level: str
    ga_measurement_id: str
    safe_mode: bool


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


def _get_env_bool(key: str, default: bool = False) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def get_settings() -> AppSettings:
    app_name = _get_secret("app", "name", _get_env("APP_NAME", "DataBuilds.dev"))
    site_url = _get_secret("app", "site_url", _get_env("SITE_URL", "https://databuilds.dev"))
    app_base_path = _get_secret("app", "base_path", _get_env("APP_BASE_PATH", ""))
    social_image_url = _get_secret(
        "app",
        "social_image_url",
        _get_env("SOCIAL_IMAGE_URL", f"{site_url.rstrip('/')}/og-image.png"),
    )
    github_url = _get_secret("links", "github", _get_env("GITHUB_URL", "https://github.com/atklaus"))
    linkedin_url = _get_secret("links", "linkedin", _get_env("LINKEDIN_URL", "https://linkedin.com/in/adam-klaus"))
    contact_email = _get_secret("links", "email", _get_env("CONTACT_EMAIL", "atk14219@gmail.com"))
    logging_level = _get_secret("logging", "level", _get_env("LOG_LEVEL", "INFO"))
    ga_measurement_id = ""
    try:
        ga_measurement_id = st.secrets.get("GA_MEASUREMENT_ID", "") or ""
        if not ga_measurement_id:
            ga_measurement_id = st.secrets.get("analytics", {}).get("ga_measurement_id", "") or ""
    except Exception:
        ga_measurement_id = ""
    ga_measurement_id = ga_measurement_id or _get_env("GA_MEASUREMENT_ID", "")
    safe_mode = _get_env_bool("APP_SAFE_MODE", False)
    return AppSettings(
        app_name=app_name,
        site_url=site_url,
        app_base_path=app_base_path,
        social_image_url=social_image_url,
        github_url=github_url,
        linkedin_url=linkedin_url,
        contact_email=contact_email,
        logging_level=logging_level,
        ga_measurement_id=ga_measurement_id,
        safe_mode=safe_mode,
    )


def email_href(email: str) -> str:
    if email.startswith("mailto:"):
        return email
    return f"mailto:{email}"
