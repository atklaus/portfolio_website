import streamlit as st


_BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700&display=swap');
:root {
  --ads-bg: #1b2626;
  --ads-surface: #1f2b2b;
  --ads-ink: #f1fbf9;
  --ads-muted: #b2c8c3;
  --ads-accent: #9be7d8;
  --ads-border: rgba(155, 231, 216, 0.18);
  --ads-shadow: rgba(0, 0, 0, 0.3);
  --ads-focus: rgba(155, 231, 216, 0.85);
}
html, body, [class*="css"] {
  font-family: 'Manrope', sans-serif;
}
html {
  scroll-behavior: smooth;
}
/* Kill the top gap inside the main page content */
div[data-testid="stMainBlockContainer"] {
  padding-top: 0 !important;
}
div[data-testid="stMainBlockContainer"] > div:first-child {
  margin-top: 0 !important;
  padding-top: 0 !important;
}
/* Streamlit often wraps content in a first vertical block */
div[data-testid="stMainBlockContainer"] .stVerticalBlock:first-child {
  margin-top: 0 !important;
  padding-top: 0 !important;
}
/* Also ensure the first element container doesn't add spacing */
div[data-testid="stMainBlockContainer"] div[data-testid="stElementContainer"]:first-child {
  margin-top: 0 !important;
  padding-top: 0 !important;
}
/* Controlled breathing room */
.main .block-container {
  padding-top: 1.25rem !important;
}
.content-shell,
.ads-shell {
  max-width: 1240px;
  margin: 0 auto;
  padding: 0 1.25rem;
}
.ads-section {
  margin: 1.35rem 0;
}
.ads-section-tight {
  margin: 0.85rem 0;
}
.ads-hero {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 2rem;
  align-items: start;
  padding: 0;
}
.hero-section {
  margin: 0.9rem 0;
}
.hero-media {
  display: flex;
  justify-content: center;
  align-items: center;
  align-self: center;
}
.ads-hero-text {
  max-width: 680px;
}
.ads-hero-title {
  margin: 0 0 0.6rem 0;
  font-size: 2.45rem;
  color: var(--ads-ink);
  font-weight: 700;
  line-height: 1.15;
}
.ads-hero-subhead {
  margin: 0 0 1rem 0;
  font-size: 1.05rem;
  color: var(--ads-accent);
  font-weight: 600;
}
.ads-hero-body {
  margin: 0 0 1.5rem 0;
  font-size: 0.98rem;
  color: var(--ads-muted);
  line-height: 1.6;
}
.section-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--ads-ink);
  margin: 0 0 0.6rem 0;
}
.ads-cta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}
.ads-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  text-decoration: none;
  color: var(--ads-ink);
  font-size: 0.9rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 0.35rem 0.85rem;
  border: 1px solid rgba(231, 243, 240, 0.25);
  background: rgba(255, 255, 255, 0.06);
}
.ads-pill:hover {
  border-color: rgba(155, 231, 216, 0.6);
  background: rgba(155, 231, 216, 0.1);
}
.ads-pill:focus-visible {
  outline: 3px solid var(--ads-focus);
  outline-offset: 3px;
}
.ads-avatar,
.hero-avatar {
  width: min(170px, 70vw);
  height: auto;
  border-radius: 24px;
  border: none;
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.28);
}
.ads-nav {
  position: sticky;
  top: 0;
  z-index: 999;
  backdrop-filter: blur(12px);
  background: rgba(27, 38, 38, 0.85);
  border-bottom: 1px solid rgba(155, 231, 216, 0.12);
}
.ads-nav-inner {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ads-nav-brand {
  color: var(--ads-ink);
  font-weight: 700;
  font-size: 1.05rem;
  letter-spacing: 0.02em;
}
.ads-nav-actions {
  display: flex;
  gap: 0.6rem;
}
.ads-icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: var(--ads-ink);
}
.ads-icon-btn:hover {
  border-color: rgba(155, 231, 216, 0.5);
  background: rgba(155, 231, 216, 0.12);
}
.ads-icon-btn:focus-visible {
  outline: 3px solid var(--ads-focus);
  outline-offset: 3px;
}
.ads-footer {
  border-top: none;
  margin-top: 0rem;
  padding: 2.25rem 0 2.25rem 0;
  background: rgba(15, 22, 22, 0.35);
}
.ads-footer-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 1.5rem;
  align-items: start;
}
.ads-footer-title {
  margin: 0 0 0.5rem 0;
  color: rgba(241, 251, 249, 0.8);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 700;
}
.ads-footer-text,
.ads-footer-link,
.ads-footer-meta {
  color: rgba(178, 200, 195, 0.85);
  font-size: 0.88rem;
  text-decoration: none;
}
.ads-footer-right {
  text-align: right;
}
.ads-labs {
  background: rgba(255, 255, 255, 0.012);
  border: none;
  border-radius: 14px;
  padding: 0.15rem 0.15rem;
  margin-top: 1.5rem;
}
.ads-labs [data-testid="stExpander"] > details {
  background: transparent;
  border: none;
  box-shadow: none;
}
.ads-labs [data-testid="stExpander"] > details > summary {
  background: transparent;
  border: none;
  border-radius: 12px;
}
.ads-labs [data-testid="stExpander"] > details[open] > summary {
  background: transparent;
}
.ads-labs [data-testid="stExpander"] > details > div {
  padding: 24px 24px 32px 24px;
}
@media (max-width: 768px) {
  .ads-hero {
    grid-template-columns: 1fr;
    gap: 1rem;
  }
  .ads-hero-title {
    font-size: 2.0rem;
  }
  .ads-hero-subhead {
    font-size: 0.98rem;
  }
  .ads-hero-body {
    font-size: 0.95rem;
  }
  .hero-avatar {
    max-width: 160px;
    margin: 0 auto;
  }
  .ads-footer-grid {
    grid-template-columns: 1fr;
  }
  .ads-footer-right {
    text-align: center;
  }
}
</style>
"""


def inject_base_styles() -> None:
    st.markdown(_BASE_CSS, unsafe_allow_html=True)
