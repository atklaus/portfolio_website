# SEO Static Files

`sitemap.xml` and `robots.txt` are published to the public R2 bucket and served
by the Cloudflare Worker at the apex domain.

The Streamlit app also injects page-level social preview metadata through
centralized SEO logic (`shared/seo.py` -> `lib/seo.py`), including:

- `og:title`, `og:description`, `og:type`, `og:url`, `og:image`
- `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`

Social image URL can be configured with:

- `SOCIAL_IMAGE_URL` env var (or `app.social_image_url` in `st.secrets`)
- default: `https://databuilds.dev/static/images/ads_logo.png`

Verification:

```bash
curl -I https://databuilds.dev/sitemap.xml
curl -I https://databuilds.dev/robots.txt
curl https://databuilds.dev/sitemap.xml | head
```

Expected:

- `200 OK`
- `Content-Type: application/xml; charset=utf-8` for `sitemap.xml`
- `Content-Type: text/plain; charset=utf-8` for `robots.txt`

Local validation:

```bash
python scripts/validate_sitemap.py
```
