from __future__ import annotations

from datetime import date
from pathlib import Path

from lib.seo import inject_social_meta
from shared.pages import get_page_by_file, get_pages, page_url
from shared.settings import get_settings
from shared.urls import app_path


def _absolute_url(base_url: str, value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    base = base_url.rstrip("/")
    if raw.startswith("/"):
        return f"{base}{raw}"
    return f"{base}/{raw}"


def apply_page_meta(page_name: str) -> None:
    settings = get_settings()
    app_base_path = getattr(settings, "app_base_path", "")
    image_url = _absolute_url(settings.site_url, settings.social_image_url)
    page = get_page_by_file(page_name)
    if page is None:
        title = settings.app_name
        description = "End-to-end data products, pipelines, and applied ML."
        url = settings.site_url.rstrip("/") + app_path("/", app_base_path)
    else:
        title = settings.app_name if page.key == "home" else f"{page.title} | {settings.app_name}"
        description = page.description
        url = page_url(page, settings.site_url, app_base_path)
    inject_social_meta(title=title, description=description, url=url, image_url=image_url)


def _sitemap_xml() -> str:
    settings = get_settings()
    today = date.today().isoformat()
    app_base_path = getattr(settings, "app_base_path", "")
    urls = [settings.site_url.rstrip("/") + "/"]
    urls.extend(
        page_url(page, settings.site_url, app_base_path)
        for page in get_pages()
        if page.include_in_sitemap and page.include_in_nav
    )
    unique_urls = list(dict.fromkeys(urls))
    lines = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    lines.extend(
        [f"  <url><loc>{url}</loc><lastmod>{today}</lastmod></url>" for url in unique_urls]
    )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def ensure_sitemap(path: str | Path = "static/sitemap.xml") -> None:
    try:
        target = Path(path)
        payload = _sitemap_xml()
        if target.exists():
            current = target.read_text()
            if current == payload:
                return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload)
    except Exception:
        pass
