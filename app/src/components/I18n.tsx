"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { type Lang, LANGS, STRINGS, type Strings } from "@/lib/i18n";
// Loaded on every page so the one-shot `beforeinstallprompt` event is caught wherever the visit starts.
import "@/lib/install";

interface Ctx {
  lang: Lang;
  t: Strings;
  setLang: (l: Lang) => void;
}

const I18nContext = createContext<Ctx>({ lang: "fr", t: STRINGS.fr, setLang: () => {} });
const KEY = "lang";

/** Stored choice first; else English for an English browser, French for everyone else. */
function initialLang(): Lang {
  try {
    const stored = window.localStorage.getItem(KEY);
    if (stored === "fr" || stored === "en") return stored;
  } catch {
    /* storage unavailable */
  }
  return (navigator.language ?? "").toLowerCase().startsWith("en") ? "en" : "fr";
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // One URL for both languages: the static HTML is French, the device choice applies after load.
  const [lang, setLangState] = useState<Lang>("fr");

  useEffect(() => {
    const l = initialLang();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate from the device once
    if (l !== "fr") setLangState(l);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem(KEY, l);
    } catch {
      /* storage unavailable */
    }
  }, []);

  return (
    <I18nContext.Provider value={{ lang, t: STRINGS[lang], setLang }}>
      {children}
    </I18nContext.Provider>
  );
}

export const useI18n = () => useContext(I18nContext);

/** "FR · EN" in the header (owner decision, 2026-11-19). */
export function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="lang" role="group" aria-label={t.common.language}>
      {LANGS.map((l) => (
        <button
          key={l}
          type="button"
          lang={l}
          className={l === lang ? "on" : undefined}
          aria-pressed={l === lang}
          onClick={() => setLang(l)}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
