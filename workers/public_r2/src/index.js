const CONTENT_TYPES = {
  html: "text/html; charset=utf-8",
  js: "application/javascript; charset=utf-8",
  mjs: "application/javascript; charset=utf-8",
  css: "text/css; charset=utf-8",
  json: "application/json; charset=utf-8",
  svg: "image/svg+xml",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  ico: "image/x-icon",
  txt: "text/plain; charset=utf-8",
  xml: "application/xml; charset=utf-8",
  map: "application/json; charset=utf-8",
  pdf: "application/pdf",
  woff: "font/woff",
  woff2: "font/woff2",
  ttf: "font/ttf",
  eot: "application/vnd.ms-fontobject",
  wasm: "application/wasm",
};

const FRAME_ANCESTORS =
  "frame-ancestors https://databuilds.dev http://localhost:8501";

const APEX_HOSTS = new Set(["databuilds.dev", "www.databuilds.dev"]);

const SEO_FILES = {
  "/": {
    key: "index.html",
    contentType: "text/html; charset=utf-8",
  },
  "/sitemap.xml": {
    key: "sitemap.xml",
    contentType: "application/xml; charset=utf-8",
  },
  "/robots.txt": {
    key: "robots.txt",
    contentType: "text/plain; charset=utf-8",
  },
  "/og-image.png": {
    key: "og-image.png",
    contentType: "image/png",
  },
  "/favicon.ico": {
    key: "favicon.ico",
    contentType: "image/x-icon",
  },
};

function contentTypeFor(key) {
  const dot = key.lastIndexOf(".");
  if (dot === -1) return null;
  const ext = key.slice(dot + 1).toLowerCase();
  return CONTENT_TYPES[ext] || null;
}

function isImmutableAsset(key) {
  return key.startsWith("assets/") || key.includes("/assets/");
}

function isNoCache(key) {
  return key.endsWith("index.html") || key.endsWith(".json");
}

function isApexHost(url) {
  return APEX_HOSTS.has(url.hostname.toLowerCase());
}

function isAppPath(pathname) {
  return pathname === "/app" || pathname.startsWith("/app/");
}

function shouldRedirectLegacyPath(pathname) {
  if (pathname === "/" || SEO_FILES[pathname] || isAppPath(pathname)) {
    return false;
  }
  const lastSegment = pathname.split("/").pop() || "";
  return !lastSegment.includes(".");
}

function _originFromEnv(env) {
  const raw = `${env.APP_ORIGIN || ""}`.trim();
  if (!raw) {
    return "";
  }
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

function _legacyRedirectUrl(url) {
  const redirected = new URL(url.toString());
  redirected.pathname = `/app${url.pathname}`.replace(/\/+/g, "/");
  return redirected.toString();
}

async function proxyToApp(request, env, url) {
  const origin = _originFromEnv(env);
  if (!origin) {
    return new Response("APP_ORIGIN is not configured.", { status: 502 });
  }

  const upstream = new URL(origin);
  upstream.pathname = url.pathname;
  upstream.search = url.search;

  const upstreamRequest = new Request(upstream.toString(), {
    method: request.method,
    headers: request.headers,
    redirect: "manual",
  });

  return fetch(upstreamRequest);
}

function buildBucketResponse(request, object, key, seoConfig) {
  const headers = new Headers();
  object.writeHttpMetadata(headers);

  const contentType = seoConfig?.contentType || contentTypeFor(key);
  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  if (isImmutableAsset(key)) {
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
  } else if (isNoCache(key) || seoConfig?.key === "sitemap.xml" || seoConfig?.key === "robots.txt") {
    headers.set("Cache-Control", "no-cache");
  }

  headers.set("Content-Security-Policy", FRAME_ANCESTORS);
  headers.delete("X-Frame-Options");

  if (object.etag) {
    headers.set("ETag", object.etag);
  }

  return new Response(request.method === "HEAD" ? null : object.body, { headers });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD" },
      });
    }

    const url = new URL(request.url);
    const apexRequest = isApexHost(url);

    if (apexRequest && url.pathname === "/app") {
      const redirected = new URL(url.toString());
      redirected.pathname = "/app/";
      return Response.redirect(redirected.toString(), 308);
    }

    if (apexRequest && shouldRedirectLegacyPath(url.pathname)) {
      return Response.redirect(_legacyRedirectUrl(url), 301);
    }

    if (apexRequest && isAppPath(url.pathname)) {
      return proxyToApp(request, env, url);
    }

    const seoConfig = SEO_FILES[url.pathname];
    let key = seoConfig ? seoConfig.key : url.pathname.replace(/^\/+/, "");
    if (key && key.endsWith("/")) {
      key += "index.html";
    }

    if (key) {
      const object = await env.PUBLIC_BUCKET.get(key);
      if (object) {
        return buildBucketResponse(request, object, key, seoConfig);
      }
    }

    if (apexRequest) {
      return proxyToApp(request, env, url);
    }

    return new Response("Not Found", { status: 404 });
  },
};
