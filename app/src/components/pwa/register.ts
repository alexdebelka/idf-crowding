// Service worker registration (production only). Kept free of React so it can be tested.

export interface RegisterEnv {
  nodeEnv: string | undefined;
  hasServiceWorker: boolean;
  secureContext: boolean;
}

/** Production builds only, in a secure context (https, or http://localhost). */
export function shouldRegister(env: RegisterEnv): boolean {
  return env.nodeEnv === "production" && env.hasServiceWorker && env.secureContext;
}

export function registerServiceWorker(): void {
  if (typeof window === "undefined") return;
  const ok = shouldRegister({
    nodeEnv: process.env.NODE_ENV,
    hasServiceWorker: "serviceWorker" in navigator,
    secureContext: window.isSecureContext,
  });
  if (!ok) return;
  const register = () => {
    // updateViaCache "none": the browser checks sw.js against the network, never the HTTP cache.
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .catch(() => {
        /* the site works without it */
      });
  };
  if (document.readyState === "complete") register();
  else window.addEventListener("load", register, { once: true });
}

/** Station id of a page path (`/p/<id>/`), else null. Same rule as the worker's. */
export function stationIdOfPath(pathname: string): string | null {
  const m = /^\/p\/([^/]+)\/?$/.exec(pathname);
  if (!m) return null;
  try {
    const id = decodeURIComponent(m[1]);
    return /^[A-Za-z0-9_-]{1,32}$/.test(id) ? id : null;
  } catch {
    return null;
  }
}

/**
 * Tells the worker that a station page is showing. A client-side link never loads the page's
 * HTML, so the worker cannot see it; it needs this to keep the station for offline use.
 */
export function notifyStationOpened(pathname: string): void {
  const id = stationIdOfPath(pathname);
  if (!id || typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  navigator.serviceWorker.ready
    .then((reg) => reg.active?.postMessage({ type: "station-opened", id }))
    .catch(() => {
      /* no worker: nothing to tell */
    });
}
