"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/components/I18n";
import { MAX_FAVOURITES, toggleFavourite, useFavourites } from "@/lib/favourites";
import type { SavedPlace } from "@/lib/saved";

/** Star in the station header: adds the station to "Vos gares" or removes it. */
export function FavouriteButton({ place }: { place: SavedPlace }) {
  const { t } = useI18n();
  const ts = t.station;
  const favs = useFavourites();
  const [note, setNote] = useState<string | null>(null);
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  // Static HTML: no star until the device list is read (it would flash the wrong state).
  if (favs === null) return <span className="fav-btn" aria-hidden="true" />;
  const on = favs.some((p) => p.id === place.id);

  const onClick = () => {
    const r = toggleFavourite(place);
    const text =
      r === "added" ? ts.favAdded : r === "removed" ? ts.favRemoved : r === "full" ? ts.favFull(MAX_FAVOURITES) : ts.favError;
    setNote(text);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNote(null), r === "full" || r === "error" ? 4500 : 2200);
  };

  return (
    <>
      <button
        type="button"
        className="fav-btn"
        aria-pressed={on}
        aria-label={on ? ts.favRemove : ts.favAdd}
        title={on ? ts.favRemove : ts.favAdd}
        onClick={onClick}
      >
        <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round">
          <path d="M12 3.2l2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 17l-5.4 2.9 1.1-6.1-4.5-4.2 6.1-.8z" />
        </svg>
      </button>
      <span role="status" className={`fav-note${note ? " fav-note-on" : ""}`}>
        {note}
      </span>
    </>
  );
}
