"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n } from "./I18n";
import { LineBadges } from "./LineBadge";
import { buildEntries, search } from "@/lib/search";
import type { IndexPlace } from "@/lib/types";

export function Search({ places }: { places: IndexPlace[] }) {
  const { t } = useI18n();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const entries = useMemo(() => buildEntries(places), [places]);
  const results = useMemo(() => search(entries, q), [entries, q]);
  const busiest = useMemo(
    () => [...places].sort((a, b) => (b.weekday_entries ?? 0) - (a.weekday_entries ?? 0)).slice(0, 12),
    [places],
  );
  const listRef = useRef<HTMLUListElement>(null);
  const shown = q.trim() ? results : busiest;

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, shown.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && shown[active]) {
      router.push(`/p/${shown[active].id}/`);
    }
  }

  return (
    <div className="search">
      <label htmlFor="q" className="sr-only">
        {t.searchLabel}
      </label>
      <div className="search-box">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M15.5 15.5 21 21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <input
          id="q"
          type="search"
          autoComplete="off"
          spellCheck={false}
          placeholder={t.searchPlaceholder}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKey}
          aria-controls="results"
          aria-activedescendant={shown[active] ? `r-${shown[active].id}` : undefined}
        />
      </div>
      {!q.trim() && <h2 className="list-title">{t.busiest}</h2>}
      {q.trim() && results.length === 0 && <p className="muted pad">{t.noResult}</p>}
      <ul id="results" className="results" ref={listRef} role="listbox">
        {shown.map((p, i) => (
          <li key={p.id} id={`r-${p.id}`} role="option" aria-selected={i === active && !!q.trim()}>
            <Link href={`/p/${p.id}/`} className={i === active && q.trim() ? "active" : ""}>
              <span className="r-name">{p.name}</span>
              <span className="r-town">{p.town}</span>
              <LineBadges lines={p.lines} size="sm" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
