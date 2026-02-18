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
  woff: "font/woff",
  woff2: "font/woff2",
  ttf: "font/ttf",
  eot: "application/vnd.ms-fontobject",
  wasm: "application/wasm",
};

const FRAME_ANCESTORS =
  "frame-ancestors https://databuilds.dev http://localhost:8501";

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

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD" },
      });
    }

    const url = new URL(request.url);
    let key = url.pathname.replace(/^\/+/, "");

    if (!key) {
      return new Response("Not Found", { status: 404 });
    }

    if (key.endsWith("/")) {
      key += "index.html";
    }

    const object = await env.PUBLIC_BUCKET.get(key);
    if (!object) {
      return new Response("Not Found", { status: 404 });
    }

    const headers = new Headers();
    object.writeHttpMetadata(headers);

    const contentType = contentTypeFor(key);
    if (contentType) {
      headers.set("Content-Type", contentType);
    }

    if (isImmutableAsset(key)) {
      headers.set("Cache-Control", "public, max-age=31536000, immutable");
    } else if (isNoCache(key)) {
      headers.set("Cache-Control", "no-cache");
    }

    headers.set("Content-Security-Policy", FRAME_ANCESTORS);
    headers.delete("X-Frame-Options");

    if (object.etag) {
      headers.set("ETag", object.etag);
    }

    return new Response(request.method === "HEAD" ? null : object.body, {
      headers,
    });
  },
};
