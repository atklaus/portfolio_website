from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class PageDef:
    key: str
    file: str
    title: str
    icon: str
    description: str
    include_in_sitemap: bool = True


def get_pages() -> list[PageDef]:
    return [
        PageDef(
            key="home",
            file="pages/0_home.py",
            title="Home",
            icon="🏠",
            description="End-to-end data products, pipelines, and applied ML with production-grade reliability.",
        ),
        PageDef(
            key="wnba_success",
            file="pages/2_wnba_success.py",
            title="WNBA Success",
            icon="🏀",
            description="Predict WNBA success from college stats with live scraping and a cached model.",
        ),
        PageDef(
            key="bibliometrix_reference_cleaner",
            file="pages/8_bibliometrix_reference_cleaner.py",
            title="Bibliometrix Cleaner",
            icon="📚",
            description="Canonicalize Scopus/WoS references for bibliometrix/Biblioshiny.",
        ),
        PageDef(
            key="landscape_img",
            file="pages/1_landscape_img.py",
            title="Landscape Prediction",
            icon="🏔️",
            description="Classify landscape images with a tiled CNN inference pipeline.",
        ),
        PageDef(
            key="game_of_life",
            file="pages/4_game_of_life.py",
            title="Game of Life",
            icon="👾",
            description="Visualize Conway's Game of Life.",
        ),
        PageDef(
            key="random_ellipses",
            file="pages/5_ellipses.py",
            title="Random Ellipses",
            icon="♾️",
            description="Monte Carlo overlap estimator for two ellipses.",
        ),
        PageDef(
            key="happy_prime",
            file="pages/6_happy_prime.py",
            title="Happy Prime",
            icon="🙂",
            description="Determine whether a number is happy and prime.",
        ),
        PageDef(
            key="analytics",
            file="pages/7_analytics.py",
            title="Analytics",
            icon="📈",
            description="Usage metrics and app activity summaries.",
        ),
        PageDef(
            key="telemetry",
            file="pages/9_telemetry_admin.py",
            title="Telemetry",
            icon="🧭",
            description="Telemetry admin and storage diagnostics.",
            include_in_sitemap=False,
        ),
    ]


def get_page_by_file(filename: str) -> PageDef | None:
    name = filename.split("/")[-1]
    for page in get_pages():
        if page.file.split("/")[-1] == name:
            return page
    return None


def page_url(page: PageDef, base_url: str) -> str:
    base = base_url.rstrip("/")
    if page.key == "home":
        return f"{base}/"
    return f"{base}/?page={quote(page.title)}"
