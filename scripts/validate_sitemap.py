from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

BASE_URL = "https://databuilds.dev/"
SITEMAP_PATH = Path(__file__).resolve().parents[1] / "static" / "sitemap.xml"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _load_locs(path: Path) -> list[str]:
    tree = ET.parse(path)
    root = tree.getroot()
    locs: list[str] = []
    for loc in root.findall("sm:url/sm:loc", SITEMAP_NS):
        if loc.text:
            locs.append(loc.text.strip())
    return locs


def main() -> int:
    if not SITEMAP_PATH.is_file():
        print(f"Error: sitemap not found at {SITEMAP_PATH}", file=sys.stderr)
        return 1

    locs = _load_locs(SITEMAP_PATH)
    errors: list[str] = []

    if not locs:
        errors.append("No <loc> entries found in sitemap.xml.")

    if BASE_URL not in locs:
        errors.append(f"Missing home URL: {BASE_URL}")

    for loc in locs:
        if not loc.startswith(BASE_URL):
            errors.append(f"Non-canonical base URL: {loc}")
        if re.search(r"/\d+_", loc):
            errors.append(f"Numeric prefix found in URL: {loc}")

    if errors:
        for message in errors:
            print(f"Error: {message}", file=sys.stderr)
        return 1

    print(f"Sitemap validation passed ({len(locs)} URLs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
