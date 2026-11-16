"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { type Lang, STRINGS, type Strings } from "@/lib/i18n";

interface Ctx {
  lang: Lang;
  t: Strings;
  setLang: (l: Lang) => void;
}

const I18nContext = createContext<Ctx>({ lang: "fr", t: STRINGS.fr, setLang: () => {} });
const KEY = "lang";

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // Static HTML is French; the stored choice (or an English browser) switches after load.
  const [lang, setLangState] = useState<Lang>("fr");

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(KEY);
    } catch {
      /* storage unavailable */
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate from storage once
    if (stored === "en") setLangState("en");
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

export function T({ k }: { k: keyof Strings }) {
  const { t } = useI18n();
  const v = t[k];
  return <>{typeof v === "string" ? v : null}</>;
}

export function LangToggle() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="lang" role="group" aria-label={t.language}>
      {(["fr", "en"] as Lang[]).map((l) => (
        <button
          key={l}
          type="button"
          className={l === lang ? "on" : ""}
          aria-pressed={l === lang}
          onClick={() => setLang(l)}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
