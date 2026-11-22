"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useI18n } from "@/components/I18n";
import { LineBadge } from "@/components/LineBadge";
import { uniqueLines } from "@/lib/format";
import { buildEntries, search } from "@/lib/search";
import type { IndexPlace } from "@/lib/types";
import { moveActive, stationHref, wantsSearchFocus } from "./logic";
import s from "./home.module.css";

const MAX_RESULTS = 8;

/** The "Quelle gare ?" field (id `recherche`) and its list of results. */
export function Search({ places, offline }: { places: IndexPlace[]; offline: boolean }) {
  const { t } = useI18n();
  const router = useRouter();
  const entries = useMemo(() => buildEntries(places), [places]);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(-1);
  const [closed, setClosed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // A press inside the list of results: the field loses focus before the tap becomes a click
  // (Safari gives the link no focus, so the blur names no target). Closing the list at that
  // moment would remove the row under the finger and the tap would open nothing.
  const pressing = useRef(false);
  const press = () => {
    pressing.current = true;
    const release = () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
      // iOS sends the blur after the finger lifts, just before the click
      window.setTimeout(() => (pressing.current = false), 500);
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
  };
  const listId = useId();
  const noteId = useId();

  const results = useMemo(() => (q.trim() ? search(entries, q, MAX_RESULTS) : []), [entries, q]);
  const showPanel = !offline && !closed && q.trim().length > 0;
  const activeId = showPanel && active >= 0 && results[active] ? `${listId}-${results[active].id}` : undefined;

  // "/#recherche" (links from the station screens): the field takes focus.
  useEffect(() => {
    const focus = () => {
      if (!wantsSearchFocus(window.location.hash)) return;
      inputRef.current?.focus();
      inputRef.current?.scrollIntoView({ block: "center" });
    };
    focus();
    window.addEventListener("hashchange", focus);
    return () => window.removeEventListener("hashchange", focus);
  }, [offline]);

  const go = (id: string) => router.push(stationHref(id));

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!results.length) return;
      e.preventDefault();
      setClosed(false);
      setActive((a) => moveActive(a, results.length, e.key as "ArrowDown" | "ArrowUp"));
    } else if (e.key === "Enter") {
      const pick = results[active >= 0 ? active : 0];
      if (showPanel && pick) {
        e.preventDefault();
        go(pick.id);
      }
    } else if (e.key === "Escape") {
      if (showPanel) {
        e.preventDefault();
        setClosed(true);
        setActive(-1);
      } else if (q) {
        setQ("");
      }
    }
  }

  return (
    <div
      className={s.searchWrap}
      onBlur={(e) => {
        if (pressing.current) return;
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setClosed(true);
      }}
    >
      <svg aria-hidden="true" className={s.searchIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.5-3.5" />
      </svg>
      <input
        ref={inputRef}
        id="recherche"
        className={`${s.field}${offline ? ` ${s.fieldOff}` : ""}`}
        type="search"
        role="combobox"
        aria-expanded={showPanel}
        aria-controls={showPanel ? listId : undefined}
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        aria-describedby={offline ? noteId : undefined}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="none"
        spellCheck={false}
        enterKeyHint="go"
        disabled={offline}
        placeholder={offline ? t.home.searchOffline : t.home.searchPlaceholder}
        value={offline ? "" : q}
        onChange={(e) => {
          setQ(e.target.value);
          setActive(-1);
          setClosed(false);
        }}
        onKeyDown={onKeyDown}
      />
      {offline ? (
        <span id={noteId} className="sr-only">
          {t.home.searchOfflineWhy}
        </span>
      ) : null}
      {showPanel ? (
        <div className={s.panel} onPointerDown={press}>
          {results.length ? (
            <ul id={listId} role="listbox" aria-label={t.home.resultsLabel} className={s.results}>
              {results.map((p, i) => (
                <li
                  key={p.id}
                  id={`${listId}-${p.id}`}
                  role="option"
                  aria-selected={i === active}
                  className={i === active ? s.rowOn : undefined}
                >
                  <Link href={stationHref(p.id)} tabIndex={-1} className={s.row}>
                    <span className={s.rowText}>
                      <span className={s.rowName}>{p.name}</span>
                      {p.town ? <span className={s.rowTown}>{p.town}</span> : null}
                    </span>
                    <span className={s.rowBadges} aria-label={t.common.lines}>
                      {uniqueLines(p.lines).map((l) => (
                        <LineBadge key={l.id} line={l} />
                      ))}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className={s.none}>{t.home.noResult}</p>
          )}
        </div>
      ) : null}
      <p className="sr-only" role="status" aria-live="polite">
        {showPanel ? (results.length ? t.home.resultsCount(results.length) : t.home.noResult) : ""}
      </p>
    </div>
  );
}
