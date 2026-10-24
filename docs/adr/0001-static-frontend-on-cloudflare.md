# Static Next.js frontend on Cloudflare, separate build host

The app is a Next.js static export (`output: 'export'`) served by Cloudflare static hosting. It reads precomputed per-Place JSON files written by the Python pipeline; there is no backend or API. A private, always-on build host runs the disruption logger, the pipeline and the daily forecast build, then pushes site + data to Cloudflare with `wrangler deploy`. Nothing on the build host is reachable from the internet, so the site stays up when the build host is down (only refreshes stop), and the API keys and the non-re-downloadable disruption archive are never exposed.

## Considered Options

- **Streamlit:** needs a running server, limited control over design.
- **Serving from a self-hosted machine via Cloudflare Tunnel:** uptime tied to home power/internet, and a web-server bug becomes a path into that machine.
- **Server-rendered Next.js on Workers (OpenNext):** unnecessary; all views (typical week, ~60-day date forecasts) are precomputable.

## Consequences

- The repo is two-language (Python pipeline in `src/`, TypeScript in `app/`). The JSON file schema is the only contract between them; version it and test it on both sides.
- If data outgrows static asset limits, move the JSON files to R2 without changing the app.
- A GitHub Action can act as a backup builder.
