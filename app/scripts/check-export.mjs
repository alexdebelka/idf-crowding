#!/usr/bin/env node
// Guard for the promise "sans traceur": run after `next build`.
//   node scripts/check-export.mjs [out-dir]        (default: out)   add --json for machine output
// Fails (exit 1) when a file of the static export could make a browser contact another origin
// (script, link, img, font, fetch, CSS url(), @import, ...), mentions a font, analytics or
// tracking host, or when the PWA files are missing. Plain <a href> links to the source and
// licence pages are allowed and listed.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** Pages a visitor may be sent to by a plain link (not requested by the page). */
export const LINK_HOSTS = ["data.iledefrance-mobilites.fr", "opendatacommons.org"];

/** A host that must not appear anywhere, even as text. */
const BANNED =
  /(?:fonts\.googleapis\.com|fonts\.gstatic\.com|gstatic\.com|googletagmanager\.com|google-analytics\.com|googleadservices\.com|doubleclick\.net|googlesyndication\.com|cloudflareinsights\.com|static\.cloudflareinsights|plausible\.io|matomo|piwik|umami\.is|posthog\.com|segment\.(?:io|com)|mixpanel\.com|amplitude\.com|hotjar\.com|clarity\.ms|fullstory\.com|sentry\.io|datadoghq|newrelic\.com|nr-data\.net|facebook\.net|connect\.facebook|linkedin\.com\/px|adobedtm|fontawesome|typekit|use\.fontawesome|bootstrapcdn|jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com)/i;

/** Absolute URLs that framework code carries as plain strings (docs links in error messages,
    XML namespaces, URL-parsing bases). They are never requested. Add to this list with care. */
const INERT_HOST =
  /^(?:www\.w3\.org|react\.dev|reactjs\.org|nextjs\.org|github\.com|developer\.mozilla\.org|tc39\.es|localhost|xn--e1aybc|[a-z])$/i;

const TEXT_EXT = new Set([
  ".html", ".txt", ".js", ".mjs", ".css", ".json", ".webmanifest", ".svg", ".xml", ".map", ".headers", "",
]);

const isAbsolute = (u) => /^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(u.trim()) || /^(?:https?|wss?|ftp):/i.test(u.trim());
const isInlineScheme = (u) => /^(?:data|blob):/i.test(u.trim());
const hostOf = (u) => {
  try {
    return new URL(u.trim().startsWith("//") ? "https:" + u.trim() : u.trim()).hostname;
  } catch {
    return "";
  }
};
const snippet = (s, i) => s.slice(Math.max(0, i - 30), i + 90).replace(/\s+/g, " ");

function* walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) yield* walk(p);
    else yield p;
  }
}

/** CSS (a file, a <style> element or a style attribute): url(...) and @import. */
function checkCss(css, where, err) {
  for (const m of css.matchAll(/url\(\s*(['"]?)([^'")]+)\1\s*\)/gi)) {
    if (isAbsolute(m[2]) && !isInlineScheme(m[2])) err(where, `CSS url() to another origin: ${m[2]}`);
  }
  for (const m of css.matchAll(/@import\s+(?:url\(\s*)?(['"]?)([^'")\s;]+)\1/gi)) {
    if (isAbsolute(m[2])) err(where, `CSS @import from another origin: ${m[2]}`);
  }
}

/** JavaScript, or Next.js payload text: absolute URLs that are not inert, and network calls with a literal absolute URL. */
function checkJs(code, where, err, links, { strict }) {
  for (const m of code.matchAll(/(?:fetch|sendBeacon|importScripts|import|open|Worker|SharedWorker|EventSource|WebSocket)\s*\(\s*(?:[^,)"'`]*,\s*)?["'`]((?:https?:|wss?:)?\/\/[^"'`]+)["'`]/g)) {
    err(where, `network call with an absolute URL: ${m[1]}`);
  }
  for (const m of code.matchAll(/(?:https?|wss?):\/\/[^\s"'`\\)<>\]}]+/g)) {
    const host = hostOf(m[0]);
    if (!strict && LINK_HOSTS.includes(host)) {
      links.set(m[0], (links.get(m[0]) ?? 0) + 1);
    } else if (strict || !INERT_HOST.test(host)) {
      err(where, `absolute URL in code: ${m[0]}`);
    }
  }
}

const URL_ATTRS = ["src", "srcset", "poster", "data", "action", "formaction", "ping", "background"];

function checkHtml(html, where, err, links) {
  // inline scripts and styles are checked on their own; remove them before reading the tags
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map((m) => m[1]);
  const styles = [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].map((m) => m[1]);
  for (const s of scripts) checkJs(s, where + " (inline script)", err, links, { strict: false });
  for (const s of styles) checkCss(s, where + " (<style>)", err);
  const markup = html.replace(/<script\b([^>]*)>[\s\S]*?<\/script>/gi, "<script$1>").replace(/<style\b([^>]*)>[\s\S]*?<\/style>/gi, "<style$1>");

  for (const tag of markup.matchAll(/<([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*)>/g)) {
    const name = tag[1].toLowerCase();
    const attrs = {};
    for (const a of tag[2].matchAll(/([^\s=/"'<>]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g)) {
      attrs[a[1].toLowerCase()] = a[2] ?? a[3] ?? a[4] ?? "";
    }
    for (const k of URL_ATTRS) {
      if (attrs[k] === undefined) continue;
      const values = k === "srcset" ? attrs[k].split(",").map((x) => x.trim().split(/\s+/)[0]) : [attrs[k]];
      for (const v of values) {
        if (isAbsolute(v) && !isInlineScheme(v)) err(where, `<${name} ${k}> to another origin: ${v}`);
      }
    }
    if (attrs.style) checkCss(attrs.style, where + " (style attribute)", err);
    if (name === "link" && attrs.href !== undefined && isAbsolute(attrs.href)) {
      const rel = (attrs.rel ?? "").toLowerCase();
      if (!/^(?:canonical|alternate)$/.test(rel)) err(where, `<link rel="${rel}"> to another origin: ${attrs.href}`);
    }
    if ((name === "use" || name === "image") && (attrs.href ?? attrs["xlink:href"]) && isAbsolute(attrs.href ?? attrs["xlink:href"])) {
      err(where, `<${name}> to another origin: ${attrs.href ?? attrs["xlink:href"]}`);
    }
    if (name === "base" && attrs.href && isAbsolute(attrs.href)) err(where, `<base> to another origin: ${attrs.href}`);
    if (name === "meta" && /refresh/i.test(attrs["http-equiv"] ?? "") && /url\s*=\s*(?:https?:)?\/\//i.test(attrs.content ?? "")) {
      err(where, `meta refresh to another origin: ${attrs.content}`);
    }
    if ((name === "a" || name === "area") && attrs.href !== undefined) {
      const href = attrs.href;
      if (isAbsolute(href)) {
        if (LINK_HOSTS.includes(hostOf(href))) links.set(href, (links.get(href) ?? 0) + 1);
        else err(where, `<a href> to a page that is not on the allowed list: ${href}`);
      } else if (/^(?:mailto|tel|javascript):/i.test(href.trim())) {
        err(where, `<a href> with a ${href.split(":")[0]}: link: ${href}`);
      }
    }
  }
}

function checkJsonValues(value, where, err, trail = "") {
  if (typeof value === "string") {
    if (isAbsolute(value) && !isInlineScheme(value)) err(where, `${trail}: absolute URL ${value}`);
  } else if (Array.isArray(value)) value.forEach((v, i) => checkJsonValues(v, where, err, `${trail}[${i}]`));
  else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) checkJsonValues(v, where, err, `${trail}.${k}`);
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  if (b.length < 24 || b.readUInt32BE(0) !== 0x89504e47) return null;
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

export function checkExport(outDir) {
  const errors = [];
  const links = new Map();
  const rel = (f) => path.relative(outDir, f).split(path.sep).join("/");
  let files = 0;

  if (!fs.existsSync(outDir)) return { errors: [{ file: outDir, message: "export folder not found (run next build)" }], links: [], files: 0 };

  for (const file of walk(outDir)) {
    files++;
    const where = rel(file);
    const ext = path.extname(file).toLowerCase();
    if (!TEXT_EXT.has(ext)) continue;
    const text = fs.readFileSync(file, "utf8");
    const err = (w, message) => errors.push({ file: w, message });
    const bm = BANNED.exec(text);
    if (bm) err(where, `banned host or tracker name: ${snippet(text, bm.index)}`);
    if (where.startsWith("data/")) continue; // published data: banned names only
    if (ext === ".html") checkHtml(text, where, err, links);
    else if (ext === ".css") checkCss(text, where, err);
    else if (where === "sw.js") checkJs(text, where, err, links, { strict: true });
    else if (ext === ".js" || ext === ".mjs" || (ext === ".txt" && /(?:^|\/)(?:__next[^/]*|index)\.txt$/.test(where))) checkJs(text, where, err, links, { strict: false });
    else if (ext === ".svg") {
      checkCss(text, where, err);
      for (const m of text.matchAll(/(?:xlink:)?href\s*=\s*["']([^"']+)["']/g)) if (isAbsolute(m[1]) && !isInlineScheme(m[1])) err(where, `SVG reference to another origin: ${m[1]}`);
    }
  }

  const need = (f, why) => {
    if (!fs.existsSync(path.join(outDir, f))) errors.push({ file: f, message: `missing: ${why}` });
    return fs.existsSync(path.join(outDir, f));
  };
  need("index.html", "home page");
  need("404.html", "not-found page");
  need("brand/favicon.svg", "favicon");
  need("fonts/onest-latin-wght-normal.woff2", "self-hosted font");
  const apple = need("icons/apple-touch-icon.png", "apple touch icon");
  if (apple) {
    const s = pngSize(path.join(outDir, "icons/apple-touch-icon.png"));
    if (!s || s.w !== 180 || s.h !== 180) errors.push({ file: "icons/apple-touch-icon.png", message: "must be a 180x180 PNG" });
  }
  if (need("sw.js", "service worker")) {
    const sw = fs.readFileSync(path.join(outDir, "sw.js"), "utf8");
    if (!/const VERSION = "[^"]+"/.test(sw)) errors.push({ file: "sw.js", message: "no cache VERSION constant" });
  }
  if (need("manifest.webmanifest", "web manifest")) {
    let m = null;
    try {
      m = JSON.parse(fs.readFileSync(path.join(outDir, "manifest.webmanifest"), "utf8"));
    } catch (e) {
      errors.push({ file: "manifest.webmanifest", message: `invalid JSON: ${e.message}` });
    }
    if (m) {
      checkJsonValues(m, "manifest.webmanifest", (w, message) => errors.push({ file: w, message }));
      for (const k of ["name", "short_name", "start_url", "scope", "display", "icons"]) {
        if (!m[k]) errors.push({ file: "manifest.webmanifest", message: `missing field ${k}` });
      }
      const icons = Array.isArray(m.icons) ? m.icons : [];
      for (const [size, purpose] of [["192x192", "any"], ["512x512", "any"], ["192x192", "maskable"], ["512x512", "maskable"]]) {
        const icon = icons.find((i) => i.sizes === size && (i.purpose ?? "any") === purpose);
        if (!icon) {
          errors.push({ file: "manifest.webmanifest", message: `no ${purpose} icon ${size}` });
          continue;
        }
        const f = path.join(outDir, icon.src.replace(/^\//, ""));
        const s = fs.existsSync(f) ? pngSize(f) : null;
        const [w, h] = size.split("x").map(Number);
        if (!s || s.w !== w || s.h !== h) errors.push({ file: icon.src, message: `missing or not a ${size} PNG` });
      }
    }
  }
  if (need("_headers", "Cloudflare headers file")) {
    const h = fs.readFileSync(path.join(outDir, "_headers"), "utf8");
    const csp = /^\s*Content-Security-Policy:\s*(.+)$/m.exec(h);
    if (!csp) errors.push({ file: "_headers", message: "no Content-Security-Policy" });
    else if (/(?:https?:|\/\/|\s\*(?:\s|;|$))/.test(csp[1])) errors.push({ file: "_headers", message: "the CSP must name 'self' only (no other origin, no wildcard)" });
    if (h.split("\n").some((l) => l.length > 2000)) errors.push({ file: "_headers", message: "a line is longer than 2,000 characters" });
    if (h.split("\n").filter((l) => /^\S/.test(l) && !l.startsWith("#")).length > 100) errors.push({ file: "_headers", message: "more than 100 rules" });
  }

  return { errors, links: [...links.entries()].sort(), files };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const args = process.argv.slice(2);
  const json = args.includes("--json");
  const dir = path.resolve(args.find((a) => !a.startsWith("--")) ?? "out");
  const r = checkExport(dir);
  if (json) {
    console.log(JSON.stringify(r, null, 2));
  } else {
    console.log(`check-export: ${r.files} files in ${dir}`);
    console.log(`plain links allowed (${LINK_HOSTS.join(", ")}): ${r.links.length} distinct`);
    for (const [u, n] of r.links) console.log(`  ${u}  (${n}x)`);
    const seen = new Set();
    for (const e of r.errors) {
      const key = `${e.message}`;
      if (seen.has(key)) continue;
      seen.add(key);
      console.log(`ERROR ${e.file}: ${e.message}`);
    }
    if (r.errors.length > seen.size) console.log(`(${r.errors.length} findings in total; identical messages shown once)`);
    console.log(r.errors.length ? `FAILED: ${r.errors.length} finding(s)` : "OK: no request to another origin, PWA files present");
  }
  process.exit(r.errors.length ? 1 : 0);
}
