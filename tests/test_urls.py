from shared.pages import PageDef, page_url
from shared.urls import app_path, normalize_base_path


def test_normalize_base_path() -> None:
    assert normalize_base_path("") == ""
    assert normalize_base_path("/") == ""
    assert normalize_base_path("app") == "/app"
    assert normalize_base_path("/app/") == "/app"


def test_app_path() -> None:
    assert app_path("/", "") == "/"
    assert app_path("/", "/app") == "/app/"
    assert app_path("/landscape_img", "/app") == "/app/landscape_img"
    assert app_path("/app/telemetry", "/app") == "/app/telemetry"


def test_page_url_respects_app_base_path() -> None:
    page = PageDef(
        key="landscape_img",
        file="pages/1_landscape_img.py",
        url_path="landscape_img",
        title="Landscape",
        icon="",
        description="desc",
    )
    assert page_url(page, "https://databuilds.dev", "/app") == "https://databuilds.dev/app/landscape_img"
