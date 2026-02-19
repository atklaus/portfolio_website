# SEO Static Files

`sitemap.xml` and `robots.txt` are published to the public R2 bucket and served
by the Cloudflare Worker at the apex domain.

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
