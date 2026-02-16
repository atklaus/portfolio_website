from __future__ import annotations

import html

import streamlit.components.v1 as components


def inject_social_meta(title: str, description: str, url: str | None = None) -> None:
    safe_title = html.escape(title or "")
    safe_desc = html.escape(description or "")
    safe_url = html.escape(url or "")

    script = f"""
    <script>
      (function() {{
        const title = '{safe_title}';
        if (title) {{
          document.title = title;
        }}
        const head = document.head || document.getElementsByTagName('head')[0];
        const ensure = (attr, name, content) => {{
          if (!content) return;
          const selector = attr === 'name' ? `meta[name='${{name}}']` : `meta[property='${{name}}']`;
          let tag = document.querySelector(selector);
          if (!tag) {{
            tag = document.createElement('meta');
            tag.setAttribute(attr, name);
            head.appendChild(tag);
          }}
          tag.setAttribute('content', content);
        }};

        ensure('property', 'og:title', '{safe_title}');
        ensure('property', 'og:description', '{safe_desc}');
        ensure('property', 'og:url', '{safe_url}');
        ensure('name', 'twitter:card', 'summary');
        ensure('name', 'twitter:title', '{safe_title}');
        ensure('name', 'twitter:description', '{safe_desc}');
      }})();
    </script>
    """
    try:
        components.html(script, height=0, width=0)
    except Exception:
        pass
