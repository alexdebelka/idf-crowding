"use client";
// Install prompt: captures `beforeinstallprompt`, tells whether an install can be offered,
// triggers it, and remembers "Plus tard" on the device (localStorage only).
import { useCallback, useEffect, useState } from "react";

/** "prompt": the browser gave us an install event; "ios": no event, show the Share-sheet hint;
 *  "none": already installed, or a browser that cannot install. */
export type InstallMode = "none" | "prompt" | "ios";

export interface InstallEnv {
  standalone: boolean;
  ios: boolean;
  hasPromptEvent: boolean;
}

export function installMode(env: InstallEnv): InstallMode {
  if (env.standalone) return "none";
  if (env.hasPromptEvent) return "prompt";
  if (env.ios) return "ios";
  return "none";
}

/** iPhone, iPod, iPad, and iPadOS posing as a Mac. */
export function isIos(ua: string, platform: string, touchPoints: number): boolean {
  if (/iPad|iPhone|iPod/.test(ua)) return true;
  return platform === "MacIntel" && touchPoints > 1;
}

export const LATER_DAYS = 30;
const DAY_MS = 86_400_000;

/** "Plus tard" hides the automatic offer for `LATER_DAYS` days. */
export function laterActive(laterAt: number | null, now: number): boolean {
  return laterAt != null && now - laterAt >= 0 && now - laterAt < LATER_DAYS * DAY_MS;
}

/** The sheet opens by itself only for a returning visitor (at least one station opened),
 *  when an install is possible and "Plus tard" has not been chosen recently. */
export function shouldAutoOffer(mode: InstallMode, hasStations: boolean, laterAt: number | null, now: number) {
  return mode !== "none" && hasStations && !laterActive(laterAt, now);
}

const KEY = "apoint:install-later";

export function readLater(): number | null {
  try {
    const n = Number(window.localStorage.getItem(KEY));
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

export function rememberLater(now = Date.now()): void {
  try {
    window.localStorage.setItem(KEY, String(now));
  } catch {
    /* storage unavailable */
  }
}

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

// The event can fire before any screen mounts: keep it at module level.
let deferred: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as BeforeInstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    notify();
  });
}

const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

export interface InstallState {
  /** `null` until the device has been read (first client render). */
  mode: InstallMode | null;
  laterAt: number | null;
  /** Shows the browser's install dialog. Resolves true when the person accepted. */
  install: () => Promise<boolean>;
  later: () => void;
}

export function useInstall(): InstallState {
  const [mode, setMode] = useState<InstallMode | null>(null);
  const [laterAt, setLaterAt] = useState<number | null>(null);

  useEffect(() => {
    const read = () => {
      setLaterAt(readLater());
      setMode(
        installMode({
          standalone: isStandalone(),
          ios: isIos(navigator.userAgent, navigator.platform, navigator.maxTouchPoints ?? 0),
          hasPromptEvent: deferred != null,
        }),
      );
    };
    read();
    listeners.add(read);
    return () => {
      listeners.delete(read);
    };
  }, []);

  const install = useCallback(async () => {
    const ev = deferred;
    if (!ev) return false;
    deferred = null; // a prompt event can be used once
    await ev.prompt();
    const { outcome } = await ev.userChoice;
    notify();
    return outcome === "accepted";
  }, []);

  const later = useCallback(() => {
    const now = Date.now();
    rememberLater(now);
    setLaterAt(now);
  }, []);

  return { mode, laterAt, install, later };
}
