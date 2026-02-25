from __future__ import annotations

import json

import streamlit.components.v1 as components


def inject_social_meta(
    title: str,
    description: str,
    url: str | None = None,
    image_url: str | None = None,
    og_type: str = "website",
) -> None:
    safe_title = title or ""
    safe_desc = description or ""
    safe_url = url or ""
    safe_image_url = image_url or ""
    safe_og_type = og_type or "website"
    twitter_card = "summary_large_image" if safe_image_url else "summary"

    script = f"""
    <script>
      (function() {{
        const title = {json.dumps(safe_title)};
        const targetDocument = (() => {{
          try {{
            if (window.parent && window.parent.document) {{
              return window.parent.document;
            }}
          }} catch (err) {{}}
          return document;
        }})();
        if (title) {{
          targetDocument.title = title;
        }}
        const head = targetDocument.head || targetDocument.getElementsByTagName('head')[0];
        if (!head) return;
        const ensure = (attr, name, content) => {{
          if (!content) return;
          const selector = attr === 'name' ? `meta[name='${{name}}']` : `meta[property='${{name}}']`;
          let tag = targetDocument.querySelector(selector);
          if (!tag) {{
            tag = targetDocument.createElement('meta');
            tag.setAttribute(attr, name);
            head.appendChild(tag);
          }}
          tag.setAttribute('content', content);
        }};
        const ensureCanonical = (href) => {{
          if (!href) return;
          let link = targetDocument.querySelector("link[rel='canonical']");
          if (!link) {{
            link = targetDocument.createElement('link');
            link.setAttribute('rel', 'canonical');
            head.appendChild(link);
          }}
          link.setAttribute('href', href);
        }};

        ensure('name', 'description', {json.dumps(safe_desc)});
        ensure('name', 'robots', 'index, follow, max-image-preview:large');
        ensure('property', 'og:title', {json.dumps(safe_title)});
        ensure('property', 'og:description', {json.dumps(safe_desc)});
        ensure('property', 'og:type', {json.dumps(safe_og_type)});
        ensure('property', 'og:url', {json.dumps(safe_url)});
        ensure('property', 'og:image', {json.dumps(safe_image_url)});
        ensure('name', 'twitter:card', {json.dumps(twitter_card)});
        ensure('name', 'twitter:title', {json.dumps(safe_title)});
        ensure('name', 'twitter:description', {json.dumps(safe_desc)});
        ensure('name', 'twitter:image', {json.dumps(safe_image_url)});
        ensure('name', 'twitter:url', {json.dumps(safe_url)});
        ensureCanonical({json.dumps(safe_url)});
      }})();
    </script>
    """
    try:
        components.html(script, height=0, width=0)
    except Exception:
        pass
