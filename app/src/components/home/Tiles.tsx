"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/components/I18n";
import { fetchPlaceFile, type SavedPlace } from "@/lib/saved";
import type { BandRule } from "@/lib/state";
import type { PlaceFile } from "@/lib/types";
import { hourKey, stationHref, tileState } from "./logic";
import s from "./home.module.css";

type Loaded = PlaceFile | "error";
const cache = new Map<string, PlaceFile>();

/** Place files of the given stations; a file that cannot be loaded is "error" (retried when the
 *  connection comes back). */
function usePlaceFiles(ids: string[], online: boolean): Record<string, Loaded | undefined> {
  const key = ids.join(",");
  const [files, setFiles] = useState<Record<string, Loaded | undefined>>({});
  useEffect(() => {
    const ctrl = new AbortController();
    for (const id of key ? key.split(",") : []) {
      if (cache.has(id)) continue; // read straight from the cache at render
      fetchPlaceFile<PlaceFile>(id, ctrl.signal)
        .then((file) => {
          cache.set(id, file);
          setFiles((f) => ({ ...f, [id]: file }));
        })
        .catch(() => {
          if (!ctrl.signal.aborted) setFiles((f) => ({ ...f, [id]: "error" }));
        });
    }
    return () => ctrl.abort();
  }, [key, online]);
  const out: Record<string, Loaded | undefined> = {};
  for (const id of ids) out[id] = files[id] ?? cache.get(id);
  return out;
}

/** The current instant, refreshed when the Paris hour changes. */
function useHourNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const tick = () => setNow((prev) => {
      const next = new Date();
      return hourKey(next) === hourKey(prev) ? prev : next;
    });
    tick();
    const timer = window.setInterval(tick, 20_000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, []);
  return now;
}

function Chevron() {
  return (
    <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={s.chevron}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function Tiles({
  stations,
  bands,
  online,
}: {
  stations: SavedPlace[];
  bands: BandRule[];
  online: boolean;
}) {
  const { t } = useI18n();
  const ids = useMemo(() => stations.map((p) => p.id), [stations]);
  const files = usePlaceFiles(ids, online);
  const now = useHourNow();

  return (
    <ul className={s.tiles}>
      {stations.map((st) => {
        const file = files[st.id];
        const state = file && file !== "error" ? tileState(file, now, bands, t.common) : null;
        if (state) {
          return (
            <li key={st.id}>
              <Link href={stationHref(st.id)} className={`${s.tile} ${state.ground === "nuit" ? s.nuit : s.signal}`}>
                <span aria-hidden="true" className={s.pA} />
                <span aria-hidden="true" className={s.pB} />
                <span className={s.tileText}>
                  <span className={s.tileName}>{state.name}</span>
                  <span className={s.tileState}>{state.headline}</span>
                  <span className={s.tileFact}>{state.fact}</span>
                </span>
                <Chevron />
              </Link>
            </li>
          );
        }
        const failed = file === "error" || (file != null && !state);
        return (
          <li key={st.id}>
            <Link href={stationHref(st.id)} className={`${s.tile} ${s.plain}`} aria-busy={!failed}>
              <span className={s.tileText}>
                <span className={s.tileName}>{st.name}</span>
                <span className={s.tileFact}>{failed ? t.home.tileUnavailable : t.home.tileLoading}</span>
              </span>
              <Chevron />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
