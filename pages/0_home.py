import os

import streamlit as st

from app import config as c
from app.shared_ui import st_utils as stu
from app.layout import header
from shared.settings import email_href, get_settings
from app.ui.cards import ProjectCard, render_project_cards
from shared.telemetry import page_guard


with page_guard(os.path.basename(__file__)):
    header.page_header('DataBuilds.dev',page_name=os.path.basename(__file__))
    # cf = CF(bucket='analytics')
    # cf.store_session(prefix='activity/{}.json.gz')

    st.markdown('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css">', unsafe_allow_html=True)
    logo_path = "static/images/ads_logo.png"
    logo_base64 = stu.get_image_base64(logo_path)

    settings = get_settings()
    github_profile_url = settings.github_url
    linkedin_profile_url = settings.linkedin_url
    email_address = email_href(settings.contact_email)

    hero_html = f"""
    <div id="home"></div>
    <div class="content-shell ads-section hero-section">
      <section class="ads-hero">
        <div class="ads-hero-text">
          <div class="ads-hero-title">Hi, I'm Adam.</div>
          <p class="ads-hero-body">
            Below is a collection of things I've built, interactive tools, data pipelines, and applied ML experiments. Hope you enjoy!
          </p>
          <div class="ads-cta-row">
            <a class="ads-pill" href="{github_profile_url}" target="_blank" rel="noopener"><i class="fab fa-github"></i> GitHub</a>
            <a class="ads-pill" href="{linkedin_profile_url}" target="_blank" rel="noopener"><i class="fab fa-linkedin"></i> LinkedIn</a>
            <a class="ads-pill" href="{email_address}" target="_blank" rel="noopener"><i class="fas fa-envelope"></i> Email</a>
          </div>
        </div>
        <div class="hero-media">
          <img class="hero-avatar" src="data:image/png;base64,{logo_base64}" alt="Adam portrait">
        </div>
      </section>
    </div>
    """
    st.markdown(hero_html, unsafe_allow_html=True)
    def _split_label(label: str) -> tuple[str, str]:
        icon = "◆"
        title = label
        parts = label.split(" ", 1)
        if len(parts) == 2 and not any(ch.isalnum() for ch in parts[0]):
            icon = parts[0]
            title = parts[1].strip()
        return icon, title


    show_mod_dict = c.MOD_ACCESS.copy()
    show_mod_dict.pop("home")
    ICON_OVERRIDES = {
        "ellipses": "🫧",
    }

    featured_cards = []
    fun_cards = []
    for mod in show_mod_dict.keys():
        mod_entry = show_mod_dict[mod]
        if mod_entry.get("hidden") or (mod_entry.get("group") or "").lower() == "admin":
            continue
        icon, title = _split_label(mod_entry["button"])
        icon = ICON_OVERRIDES.get(mod_entry["name"], icon)
        tags = tuple(mod_entry.get("tags", ()))
        group = (mod_entry.get("group") or "fun").lower()
        card = ProjectCard(
            title=title,
            description=mod_entry["description"],
            icon=icon,
            destination=header.get_page_path(mod_entry["name"]),
            tags=tags,
        )
        if group == "featured":
            featured_cards.append(card)
        else:
            fun_cards.append(card)

    if featured_cards:
        st.markdown('<div id="featured"></div><div class="content-shell ads-section-tight"><h3 class="section-title">Featured Projects</h3>', unsafe_allow_html=True)
        render_project_cards(featured_cards)
        st.markdown('</div>', unsafe_allow_html=True)

    if fun_cards:
        st.markdown('<div id="fun"></div><div class="content-shell ads-section-tight ads-labs">', unsafe_allow_html=True)
        with st.expander("Other fun projects"):
            render_project_cards(fun_cards)
        st.markdown('</div>', unsafe_allow_html=True)

    footer_html = f"""
    <div id="contact"></div>
    <div class="ads-footer">
      <div class="content-shell">
        <div class="ads-footer-grid">
          <div>
            <div class="ads-footer-title">Contact</div>
            <a class="ads-footer-link" href="{email_address}" target="_blank" rel="noopener">Email</a>
          </div>
          <div>
            <div class="ads-footer-title">About</div>
            <div class="ads-footer-text">Built with Streamlit and hosted on DigitalOcean.</div>
          </div>
          <div class="ads-footer-right">
            <div class="ads-footer-title">© 2026</div>
            <div class="ads-footer-meta">databuilds.dev</div>
          </div>
      </div>
      </div>
    </div>
    """

    st.markdown(footer_html, unsafe_allow_html=True)
