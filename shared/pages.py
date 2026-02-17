from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from app import config as app_config


@dataclass(frozen=True)
class PageDef:
    key: str
    file: str
    title: str
    icon: str
    description: str
    include_in_nav: bool = True
    include_in_sitemap: bool = True


_DEFAULT_ICON = "📄"
_DEFAULT_DESCRIPTION = "Explore data products, pipelines, and applied ML."

_OVERRIDES: dict[str, dict[str, object]] = {
    "home": {
        "key": "home",
        "title": "Home",
        "icon": "🏠",
        "description": "End-to-end data products, pipelines, and applied ML with production-grade reliability.",
    },
    "telemetry_admin": {
        "key": "telemetry",
        "title": "Site Analytics",
        "icon": "🧭",
        "description": "Telemetry admin and storage diagnostics.",
        "include_in_sitemap": False,
        "include_in_nav": True,
    },
}


def _split_label(label: str) -> tuple[str, str]:
    icon = _DEFAULT_ICON
    title = label.strip()
    parts = label.split(" ", 1)
    if len(parts) == 2 and not any(ch.isalnum() for ch in parts[0]):
        icon = parts[0]
        title = parts[1].strip()
    return icon, title or icon


def _mod_lookup() -> dict[str, dict]:
    mods: dict[str, dict] = {}
    for entry in app_config.MOD_ACCESS.values():
        name = entry.get("name")
        if not name:
            continue
        mods[name] = entry
    return mods


def _parse_page(path: Path, mods: dict[str, dict]) -> tuple[int, str, PageDef]:
    stem = path.stem
    match = re.match(r"^(?P<num>\\d+)_?(?P<slug>.+)$", stem)
    if match:
        order = int(match.group("num"))
        slug = match.group("slug")
    else:
        order = 999
        slug = stem

    mod = mods.get(slug)
    if mod:
        icon, title = _split_label(mod.get("button", ""))
        description = mod.get("description", _DEFAULT_DESCRIPTION)
    else:
        icon = _DEFAULT_ICON
        title = slug.replace("_", " ").title()
        description = _DEFAULT_DESCRIPTION

    override = _OVERRIDES.get(slug, {})
    key = override.get("key", slug)
    include_in_nav = bool(override.get("include_in_nav", True))
    if mod and isinstance(mod, dict) and mod.get("enabled") is False:
        include_in_nav = False
    page = PageDef(
        key=str(key),
        file=str(Path("pages") / path.name),
        title=str(override.get("title", title)),
        icon=str(override.get("icon", icon)),
        description=str(override.get("description", description)),
        include_in_nav=include_in_nav,
        include_in_sitemap=bool(override.get("include_in_sitemap", True)),
    )
    return order, slug, page


def get_pages(pages_dir: str | Path = "pages") -> list[PageDef]:
    pages_path = Path(pages_dir)
    mods = _mod_lookup()
    pages: list[tuple[int, str, PageDef]] = []
    if pages_path.exists():
        for path in pages_path.glob("*.py"):
            pages.append(_parse_page(path, mods))
    pages.sort(key=lambda item: (item[0], item[1]))
    return [page for _, _, page in pages]


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
