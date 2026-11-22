"use client";
// The intro animation (public/brand/intro.js, a self-contained SVG scene). Loaded only when it
// is about to play, from the site's own origin.

export interface IntroHandle {
  play: () => void;
  draw: (seconds: number) => void;
  destroy: () => void;
  duration: number;
}

interface IntroApi {
  mount: (host: HTMLElement, opt: Record<string, unknown>) => IntroHandle;
  duration: number;
}

let loading: Promise<IntroApi> | null = null;

export function loadIntro(): Promise<IntroApi> {
  if (loading) return loading;
  loading = new Promise<IntroApi>((resolve, reject) => {
    const w = window as unknown as { IntroV2?: IntroApi };
    if (w.IntroV2) return resolve(w.IntroV2);
    const el = document.createElement("script");
    el.src = "/brand/intro.js";
    el.async = true;
    el.onload = () => (w.IntroV2 ? resolve(w.IntroV2) : reject(new Error("intro: no api")));
    el.onerror = () => reject(new Error("intro: load failed"));
    document.head.appendChild(el);
  });
  loading.catch(() => {
    loading = null;
  });
  return loading;
}

/** Wordmark set in Onest, no tagline. The em values place the rabbit against Onest's letters. */
export const INTRO_OPTIONS = {
  name: "à point",
  tagline: "",
  wordFont: "Onest, system-ui, sans-serif",
  ascender: 0.72,
  descender: 0.2,
  xHeight: 0.52,
};

export const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Onest must be ready before the scene measures the wordmark. */
export async function introReady(): Promise<IntroApi> {
  const [api] = await Promise.all([
    loadIntro(),
    document.fonts.load("700 176px Onest").catch(() => undefined),
  ]);
  return api;
}

// Launch splash of the installed app: the end of the run, the bloom and the lockup.
export const SPLASH_FROM = 2.3;
export const SPLASH_TO = 5.6;
export const SPLASH_SPEED = 1.3;
export const SPLASH_KEY = "intro-seen";

/** Scene time for a splash that has been running `elapsed` seconds; null when it is over. */
export function splashTime(elapsed: number): number | null {
  const t = SPLASH_FROM + elapsed * SPLASH_SPEED;
  return t >= SPLASH_TO ? null : t;
}
