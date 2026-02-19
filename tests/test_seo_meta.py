from __future__ import annotations

from types import SimpleNamespace

from lib import seo as lib_seo
from shared import seo as shared_seo


def test_inject_social_meta_includes_open_graph_and_twitter_image_tags(monkeypatch):
    captured: dict[str, str] = {}

    def _capture_html(payload: str, *, height: int, width: int) -> None:
        captured["payload"] = payload

    monkeypatch.setattr(lib_seo.components, "html", _capture_html)

    lib_seo.inject_social_meta(
        title="DataBuilds.dev",
        description="Data engineering and ML systems.",
        url="https://databuilds.dev",
        image_url="https://databuilds.dev/static/images/ads_logo.png",
    )

    payload = captured["payload"]
    assert "window.parent" in payload
    assert "og:title" in payload
    assert "og:description" in payload
    assert "og:type" in payload
    assert "og:url" in payload
    assert "og:image" in payload
    assert "twitter:image" in payload
    assert "summary_large_image" in payload


def test_inject_social_meta_uses_summary_card_without_image(monkeypatch):
    captured: dict[str, str] = {}

    def _capture_html(payload: str, *, height: int, width: int) -> None:
        captured["payload"] = payload

    monkeypatch.setattr(lib_seo.components, "html", _capture_html)

    lib_seo.inject_social_meta(
        title="DataBuilds.dev",
        description="Data engineering and ML systems.",
        url="https://databuilds.dev",
    )

    payload = captured["payload"]
    assert "summary_large_image" not in payload
    assert '"summary"' in payload


def test_apply_page_meta_passes_absolute_social_image_url(monkeypatch):
    settings = SimpleNamespace(
        app_name="DataBuilds.dev",
        site_url="https://databuilds.dev",
        social_image_url="/static/images/ads_logo.png",
    )
    page = SimpleNamespace(
        key="home",
        title="Home",
        description="Landing page",
    )
    captured: dict[str, str] = {}

    monkeypatch.setattr(shared_seo, "get_settings", lambda: settings)
    monkeypatch.setattr(shared_seo, "get_page_by_file", lambda _name: page)
    monkeypatch.setattr(shared_seo, "page_url", lambda _page, _base: "https://databuilds.dev/")
    monkeypatch.setattr(shared_seo, "inject_social_meta", lambda **kwargs: captured.update(kwargs))

    shared_seo.apply_page_meta("pages/0_home.py")

    assert captured["title"] == "DataBuilds.dev"
    assert captured["description"] == "Landing page"
    assert captured["url"] == "https://databuilds.dev/"
    assert captured["image_url"] == "https://databuilds.dev/static/images/ads_logo.png"
