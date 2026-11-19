// scripts/check-export.mjs on small synthetic exports: it must pass a clean one and fail
// each way of reaching another origin.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

const app = fileURLToPath(new URL("..", import.meta.url));
const script = path.join(app, "scripts/check-export.mjs");
const dirs: string[] = [];

function pngOf(size: number): Buffer {
  const b = Buffer.alloc(33);
  b.writeUInt32BE(0x89504e47, 0);
  b.writeUInt32BE(size, 16);
  b.writeUInt32BE(size, 20);
  return b;
}

/** A minimal export that passes; `extra` adds or replaces files. */
function makeExport(extra: Record<string, string> = {}): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "check-export-"));
  dirs.push(dir);
  const manifest = JSON.parse(fs.readFileSync(path.join(app, "public/manifest.webmanifest"), "utf8"));
  const files: Record<string, string | Buffer> = {
    "index.html": '<!DOCTYPE html><html><head><link rel="stylesheet" href="/_next/static/a.css"/><link rel="manifest" href="/manifest.webmanifest"/></head><body><a href="https://opendatacommons.org/licenses/odbl/1-0/">ODbL</a><script src="/_next/static/a.js"></script><script>self.__next_f.push([1,"x"])</script></body></html>',
    "404.html": "<html><body>404</body></html>",
    "_next/static/a.css": '@font-face{src:url("/fonts/onest-latin-wght-normal.woff2")}',
    "_next/static/a.js": 'console.log("see https://react.dev/errors/1"); fetch("/data/index.json")',
    "fonts/onest-latin-wght-normal.woff2": "x",
    "brand/favicon.svg": '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>',
    "icons/apple-touch-icon.png": pngOf(180),
    "icons/icon-192.png": pngOf(192),
    "icons/icon-512.png": pngOf(512),
    "icons/icon-maskable-192.png": pngOf(192),
    "icons/icon-maskable-512.png": pngOf(512),
    "manifest.webmanifest": JSON.stringify(manifest),
    "sw.js": 'const VERSION = "v1";\n',
    "_headers": "/*\n  Content-Security-Policy: default-src 'self'; connect-src 'self'\n",
    "data/index.json": '{"a":1}',
    ...extra,
  };
  for (const [name, content] of Object.entries(files)) {
    const f = path.join(dir, name);
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, content);
  }
  return dir;
}

function run(dir: string) {
  const r = spawnSync(process.execPath, [script, dir, "--json"], { encoding: "utf8" });
  const out = JSON.parse(r.stdout) as { errors: { file: string; message: string }[]; links: [string, number][] };
  return { code: r.status, ...out };
}

afterAll(() => {
  for (const d of dirs) fs.rmSync(d, { recursive: true, force: true });
});

describe("check-export", () => {
  it("passes a clean export and lists the plain links", () => {
    const r = run(makeExport());
    expect(r.errors).toEqual([]);
    expect(r.code).toBe(0);
    expect(r.links.map((l) => l[0])).toEqual(["https://opendatacommons.org/licenses/odbl/1-0/"]);
  });

  const bad: [string, Record<string, string>, RegExp][] = [
    ["a script from another origin", { "index.html": '<html><script src="https://cdn.example.com/x.js"></script></html>' }, /another origin/],
    ["a protocol-relative stylesheet", { "index.html": '<html><link rel="stylesheet" href="//cdn.example.com/x.css"></html>' }, /another origin/],
    ["an image from another origin", { "index.html": '<html><img src="https://img.example.com/x.png"></html>' }, /another origin/],
    ["a srcset entry", { "index.html": '<html><img srcset="/a.png 1x, https://img.example.com/b.png 2x"></html>' }, /another origin/],
    ["a preconnect", { "index.html": '<html><link rel="preconnect" href="https://fonts.example.com"></html>' }, /another origin/],
    ["a CSS url()", { "_next/static/a.css": "a{background:url(https://img.example.com/x.png)}" }, /CSS url/],
    ["a CSS @import", { "_next/static/a.css": '@import "https://x.example.com/a.css";' }, /@import/],
    ["a style attribute", { "index.html": '<html><div style="background:url(https://i.example.com/a.png)"></div></html>' }, /CSS url/],
    ["a fetch to another origin", { "_next/static/a.js": 'fetch("https://api.example.com/v1")' }, /network call/],
    ["an absolute URL in code", { "_next/static/a.js": 'const u = "https://api.example.com/v1"' }, /absolute URL in code/],
    ["an inline script that loads a script", { "index.html": '<html><script>s.src="https://cdn.example.com/a.js"</script></html>' }, /absolute URL/],
    ["an <a href> to another page", { "index.html": '<html><a href="https://example.com/">x</a></html>' }, /allowed list/],
    ["a Google Fonts host", { "_next/static/a.css": "/* https://fonts.googleapis.com/css2 */" }, /banned/],
    ["an analytics host", { "_next/static/a.js": 'var a = "plausible.io"' }, /banned/],
    ["an analytics host in the data", { "data/index.json": '{"u":"https://www.google-analytics.com/"}' }, /banned/],
    ["an absolute URL in the manifest", { "manifest.webmanifest": '{"name":"a","short_name":"a","start_url":"https://x.example.com/","scope":"/","display":"standalone","icons":[]}' }, /absolute URL/],
    ["an absolute URL in the service worker", { "sw.js": 'const VERSION = "v1";\nfetch("https://x.example.com/")' }, /sw\.js|absolute|network/],
    ["a CSP that names another origin", { "_headers": "/*\n  Content-Security-Policy: default-src 'self' https://cdn.example.com\n" }, /CSP/],
  ];
  for (const [name, files, message] of bad) {
    it(`fails on ${name}`, () => {
      const r = run(makeExport(files));
      expect(r.code).toBe(1);
      expect(r.errors.map((e) => e.message).join("\n")).toMatch(message);
    });
  }

  it("fails when the PWA files are missing", () => {
    const dir = makeExport();
    for (const f of ["manifest.webmanifest", "sw.js", "icons/icon-512.png", "icons/apple-touch-icon.png", "_headers"]) {
      fs.rmSync(path.join(dir, f));
    }
    const r = run(dir);
    expect(r.code).toBe(1);
    const text = r.errors.map((e) => `${e.file}: ${e.message}`).join("\n");
    for (const f of ["manifest.webmanifest", "sw.js", "apple-touch-icon.png", "_headers"]) expect(text).toContain(f);
  });

  it("fails when an icon has the wrong size", () => {
    const r = run(makeExport({ "icons/icon-512.png": pngOf(100) as unknown as string }));
    expect(r.code).toBe(1);
    expect(r.errors.map((e) => e.message).join("\n")).toMatch(/512x512 PNG/);
  });
});
