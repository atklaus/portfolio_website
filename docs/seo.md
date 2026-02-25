# SEO + Search Setup

The apex domain serves a static SEO landing page while Streamlit runs under
`/app`. This avoids search engines indexing the default Streamlit shell.

## Architecture

- `https://databuilds.dev/` -> static `index.html` from R2 (server-rendered meta tags)
- `https://databuilds.dev/app/...` -> Streamlit app proxied through Worker
- `robots.txt`, `sitemap.xml`, `og-image.png`, `favicon.ico` -> served from R2 at apex

## Static SEO Assets

Published by `scripts/publish_seo_static.py`:

- `static/index.html` -> `https://databuilds.dev/`
- `static/sitemap.xml` -> `https://databuilds.dev/sitemap.xml`
- `static/robots.txt` -> `https://databuilds.dev/robots.txt`
- `static/images/og_image_1200x630.png` -> `https://databuilds.dev/og-image.png`
- `static/images/favicon.ico` -> `https://databuilds.dev/favicon.ico`

## Runtime SEO Metadata

The Streamlit app still injects page-level Open Graph and Twitter tags through
`shared/seo.py` -> `lib/seo.py` for in-app routes:

- `og:title`, `og:description`, `og:type`, `og:url`, `og:image`
- `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`
- `description`, `robots`, and canonical link

Configuration:

- `SITE_URL` (default `https://databuilds.dev`)
- `APP_BASE_PATH` (production: `/app`)
- `SOCIAL_IMAGE_URL` (default `https://databuilds.dev/og-image.png`)

## Verify

```bash
curl -I https://databuilds.dev/
curl -I https://databuilds.dev/sitemap.xml
curl -I https://databuilds.dev/robots.txt
curl -I https://databuilds.dev/og-image.png
curl -I https://databuilds.dev/app/
```

Expected:

- `200 OK` on all endpoints above
- `Content-Type: text/html` for `/`
- `Content-Type: application/xml; charset=utf-8` for `/sitemap.xml`
- `Content-Type: text/plain; charset=utf-8` for `/robots.txt`
- `Content-Type: image/png` for `/og-image.png`

Local sitemap validation:

```bash
python scripts/validate_sitemap.py
```
