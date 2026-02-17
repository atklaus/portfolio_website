from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

from app.shared_ui import st_utils


@dataclass(frozen=True)
class ProjectCard:
    title: str
    description: str
    icon: str
    destination: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    external: bool | None = None


_CARD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600&display=swap');
:root {
    --ads-ink: #e7f3f0;
    --ads-muted: #a8c0bb;
    --ads-border: rgba(255, 255, 255, 0.1);
    --ads-shadow: rgba(0, 0, 0, 0.35);
    --ads-focus: rgba(155, 231, 216, 0.85);
}
@media (prefers-color-scheme: light) {
  :root {
    --ads-ink: #0f1f1c;
    --ads-muted: #3b4a47;
    --ads-border: rgba(15, 31, 28, 0.12);
    --ads-shadow: rgba(8, 14, 13, 0.15);
    --ads-focus: rgba(22, 120, 102, 0.5);
  }
}
html, body, [class*="css"] {
    font-family: 'Manrope', sans-serif;
}
.ads-card-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1.25rem;
}
@media (max-width: 1100px) {
  .ads-card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 768px) {
  .ads-card-grid { grid-template-columns: 1fr; }
}
.ads-card {
    display: flex;
    flex-direction: column;
    text-decoration: none;
    color: inherit;
    cursor: pointer;
    border-radius: 22px;
    overflow: hidden;
    border: 1px solid var(--ads-border);
    background: radial-gradient(circle at top left, rgba(155, 231, 216, 0.12), transparent 55%),
                linear-gradient(160deg, #203635, #1b2626 55%);
    min-height: 175px;
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    text-decoration: none;
}
.ads-card,
.ads-card:visited,
.ads-card:hover,
.ads-card:active,
.ads-card * {
    text-decoration: none !important;
}
.ads-card:focus-visible {
    outline: 3px solid var(--ads-focus);
    outline-offset: 4px;
    text-decoration: none;
}
.ads-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 12px 28px var(--ads-shadow);
    border-color: rgba(155, 231, 216, 0.35);
}
.ads-card-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.9rem;
    background: linear-gradient(120deg, rgba(155, 231, 216, 0.28), rgba(49, 107, 98, 0.35));
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.ads-card-header-title {
    font-size: 1.02rem;
    font-weight: 600;
    color: var(--ads-ink);
    text-decoration: none;
}
.ads-card-header-spacer {
    flex: 1;
}
.ads-card-header-arrow {
    font-size: 1.1rem;
    color: var(--ads-ink);
    opacity: 0;
    transition: opacity 0.2s ease, transform 0.2s ease;
}
.ads-card:hover .ads-card-header-arrow {
    opacity: 0.9;
    transform: translateX(3px);
}
.ads-card-body {
    padding: 0.7rem 1rem 0.95rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
}
.ads-card-icon {
    width: 44px;
    height: 44px;
    border-radius: 14px;
    display: grid;
    place-items: center;
    font-size: 1.2rem;
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.2);
    box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.2);
}
.ads-card-icon img {
    width: 70%;
    height: 70%;
    object-fit: contain;
}
.ads-card-desc {
    font-size: 0.88rem;
    color: var(--ads-muted);
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.4rem;
    text-decoration: none;
}
.ads-card-tags {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 0.35rem;
}
.ads-card-tag {
    font-size: 0.72rem;
    letter-spacing: 0.02em;
    padding: 0.18rem 0.65rem;
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: var(--ads-ink);
    opacity: 0.8;
}
</style>
"""


def _is_external(destination: str) -> bool:
    return destination.startswith("http://") or destination.startswith("https://")


def _icon_html(icon: str) -> str:
    if not icon:
        return ""
    if any(icon.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".svg", ".webp")):
        path = Path(icon)
        if path.exists():
            b64 = st_utils.get_image_base64(str(path))
            return f"<img src=\"data:image/png;base64,{b64}\" alt=\"\" />"
    return icon


def render_project_cards(cards: list[ProjectCard]) -> None:
    if not cards:
        return

    st.markdown(_CARD_CSS, unsafe_allow_html=True)

    html = ['<div class="ads-card-grid">']
    for card in cards:
        is_external = card.external if card.external is not None else _is_external(card.destination)
        if is_external:
            href = card.destination
            target = ' target="_blank" rel="noopener"'
        else:
            href = card.destination
            target = ' target="_self"'

        icon_html = _icon_html(card.icon)
        tags_html = ""
        if card.tags:
            tags = "".join(f"<span class=\"ads-card-tag\">{tag}</span>" for tag in card.tags)
            tags_html = f"<div class=\"ads-card-tags\">{tags}</div>"

        html.append(
            f"""
<a class="ads-card" href="{href}" aria-label="Open {card.title}"{target}>
  <div class="ads-card-header">
    <div class="ads-card-icon">{icon_html}</div>
    <div class="ads-card-header-title">{card.title}</div>
    <div class="ads-card-header-spacer"></div>
    <div class="ads-card-header-arrow" aria-hidden="true">→</div>
  </div>
  <div class="ads-card-body">
    <div class="ads-card-desc">{card.description}</div>
    {tags_html}
  </div>
</a>
"""
        )
    html.append("</div>")

    st.markdown("".join(html), unsafe_allow_html=True)
