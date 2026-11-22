// Manifest, icons, Cloudflare headers and wrangler config: what can be checked without a deploy.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const app = fileURLToPath(new URL("..", import.meta.url));
const read = (p: string) => fs.readFileSync(path.join(app, p), "utf8");
const png = (p: string) => {
  const b = fs.readFileSync(path.join(app, p));
  return { sig: b.readUInt32BE(0), w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
};

interface Icon {
  src: string;
  sizes: string;
  type: string;
  purpose?: string;
}
const manifest = JSON.parse(read("public/manifest.webmanifest")) as Record<string, unknown> & { icons: Icon[] };

describe("web manifest", () => {
  it("names the app and keeps it in scope", () => {
    expect(manifest.name).toBe("à point");
    expect(manifest.short_name).toBe("à point");
    expect(manifest.lang).toBe("fr");
    expect(manifest.start_url).toBe("/");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
    expect(manifest.background_color).toBe("#F6F7F4");
    expect(manifest.theme_color).toBe("#F6F7F4");
    expect(String(manifest.description)).toMatch(/sans traceur/);
  });
  it("has 192 and 512 icons, any and maskable, that exist with the declared size", () => {
    for (const size of [192, 512]) {
      for (const purpose of ["any", "maskable"]) {
        const icon = manifest.icons.find((i) => i.sizes === `${size}x${size}` && (i.purpose ?? "any") === purpose);
        expect(icon, `${purpose} ${size}`).toBeTruthy();
        const s = png("public" + icon!.src);
        expect(s.sig).toBe(0x89504e47);
        expect([s.w, s.h]).toEqual([size, size]);
      }
    }
  });
  it("has an apple touch icon of 180 px, the one the layout links", () => {
    const s = png("public/icons/apple-touch-icon.png");
    expect([s.w, s.h]).toEqual([180, 180]);
    expect(read("src/app/layout.tsx")).toContain("/icons/apple-touch-icon.png");
    expect(read("src/app/layout.tsx")).toContain("/manifest.webmanifest");
  });
  it("uses no absolute URL", () => {
    expect(JSON.stringify(manifest)).not.toMatch(/https?:\/\//);
  });
});

describe("_headers", () => {
  const text = read("public/_headers");
  const lines = text.split("\n");
  const blocks: Record<string, string[]> = {};
  let current = "";
  for (const l of lines) {
    if (!l.trim() || l.startsWith("#")) continue;
    if (/^\S/.test(l)) {
      current = l.trim();
      blocks[current] = [];
    } else blocks[current].push(l.trim());
  }
  const header = (pattern: string, name: string) =>
    blocks[pattern]?.find((x) => x.toLowerCase().startsWith(name.toLowerCase() + ":"))?.slice(name.length + 1).trim();

  it("respects the Cloudflare limits", () => {
    expect(Object.keys(blocks).length).toBeLessThanOrEqual(100);
    for (const l of lines) expect(l.length).toBeLessThanOrEqual(2000);
  });
  it("has a CSP that allows only the site's own origin", () => {
    const csp = header("/*", "Content-Security-Policy")!;
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toMatch(/https?:|\/\/|\*|unsafe-eval/);
    // Next.js static export inlines its bootstrap script: stated trade-off
    expect(csp).toContain("script-src 'self' 'unsafe-inline'");
  });
  it("has the other security headers", () => {
    expect(header("/*", "Referrer-Policy")).toBe("no-referrer");
    expect(header("/*", "X-Content-Type-Options")).toBe("nosniff");
    expect(header("/*", "Permissions-Policy")).toMatch(/camera=\(\)/);
  });
  it("caches the right things for the right time", () => {
    expect(header("/_next/static/*", "Cache-Control")).toMatch(/max-age=31536000.*immutable/);
    expect(header("/fonts/*", "Cache-Control")).toMatch(/max-age=31536000/);
    expect(header("/data/*", "Cache-Control")).toMatch(/max-age=300.*must-revalidate/);
    expect(header("/sw.js", "Cache-Control")).toMatch(/max-age=0/);
    expect(header("/manifest.webmanifest", "Cache-Control")).toMatch(/max-age=0/);
  });
  it("never sets Cache-Control twice for one URL (Cloudflare would join the values with a comma)", () => {
    const withCache = Object.keys(blocks).filter((p) => header(p, "Cache-Control"));
    const probes = ["/_next/static/chunks/a.js", "/fonts/a.woff2", "/brand/mark.svg", "/icons/a.png", "/data/index.json", "/data/places/1.json", "/sw.js", "/manifest.webmanifest", "/", "/p/1/"];
    const matches = (pattern: string, url: string) => new RegExp("^" + pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$").test(url);
    for (const url of probes) {
      expect(withCache.filter((p) => matches(p, url)).length, url).toBeLessThanOrEqual(1);
    }
  });
});

describe("wrangler.jsonc", () => {
  const cfg = JSON.parse(read("wrangler.jsonc").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/ .*$/gm, ""));
  it("serves the static export; the Worker script only answers /api/* (ADR 0004)", () => {
    expect(cfg.assets.directory).toBe("./out");
    expect(cfg.assets.html_handling).toBe("auto-trailing-slash");
    expect(cfg.assets.not_found_handling).toBe("404-page");
    expect(cfg.main).toBe("./worker/index.ts");
    expect(cfg.assets.binding).toBe("ASSETS");
    // pages, data and the service worker stay static asset requests: _headers applies to them
    expect(cfg.assets.run_worker_first).toEqual(["/api/*"]);
  });
});
