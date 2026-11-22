"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/components/I18n";
import { moveFavourite, removeFavourite } from "@/lib/favourites";
import type { SavedPlace } from "@/lib/saved";
import s from "./home.module.css";

type Action = "up" | "down" | "remove";

function Icon({ action }: { action: Action }) {
  const d = action === "up" ? "M6 15l6-6 6 6" : action === "down" ? "M6 9l6 6 6-6" : "M18 6L6 18M6 6l12 12";
  return (
    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

/** "Vos gares" in edit mode: one row per favourite with up, down and remove buttons (44 px).
 *  Buttons, not drag and drop: they work the same with touch, mouse, keyboard and screen
 *  readers. Each change is written to the device at once, like the star. */
export function FavouritesEditor({ stations }: { stations: SavedPlace[] }) {
  const { t } = useI18n();
  const th = t.home;
  const list = useRef<HTMLOListElement>(null);
  const [focus, setFocus] = useState<{ id: string; action: Action } | null>(null);
  const [said, setSaid] = useState("");

  // A moved row keeps the focus on its button; at the top or bottom that button is disabled,
  // so the focus goes to the other arrow. After a removal it goes to the next row.
  useEffect(() => {
    if (!focus || !list.current) return;
    const row = list.current.querySelector<HTMLElement>(`[data-id="${focus.id}"]`);
    const pick = (a: Action) => row?.querySelector<HTMLButtonElement>(`button[data-action="${a}"]:not(:disabled)`);
    const other: Action = focus.action === "up" ? "down" : "up";
    (pick(focus.action) ?? pick(other) ?? pick("remove"))?.focus();
  }, [focus, stations]);

  const act = (st: SavedPlace, i: number, action: Action) => {
    if (action === "remove") {
      removeFavourite(st.id);
      const next = stations[i + 1] ?? stations[i - 1];
      setFocus(next ? { id: next.id, action: "remove" } : null);
      setSaid(th.favRemoved(st.name));
      return;
    }
    const delta = action === "up" ? -1 : 1;
    moveFavourite(st.id, delta);
    setFocus({ id: st.id, action });
    setSaid(th.favMoved(st.name, i + 1 + delta, stations.length));
  };

  return (
    <>
      <ol ref={list} className={s.editList} aria-label={th.favEditLabel}>
        {stations.map((st, i) => (
          <li key={st.id} data-id={st.id} className={s.editRow}>
            <span className={s.editName}>{st.name}</span>
            <span className={s.editButtons}>
              <button type="button" className={s.editBtn} data-action="up" disabled={i === 0} aria-label={th.favMoveUp(st.name)} onClick={() => act(st, i, "up")}>
                <Icon action="up" />
              </button>
              <button
                type="button"
                className={s.editBtn}
                data-action="down"
                disabled={i === stations.length - 1}
                aria-label={th.favMoveDown(st.name)}
                onClick={() => act(st, i, "down")}
              >
                <Icon action="down" />
              </button>
              <button type="button" className={`${s.editBtn} ${s.editRemove}`} data-action="remove" aria-label={th.favRemove(st.name)} onClick={() => act(st, i, "remove")}>
                <Icon action="remove" />
              </button>
            </span>
          </li>
        ))}
      </ol>
      <p role="status" className="sr-only">
        {said}
      </p>
    </>
  );
}
