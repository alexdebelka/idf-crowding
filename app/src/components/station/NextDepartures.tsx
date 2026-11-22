"use client";
// Next departures in real time, under the chart of the "now" view. Asks the site's own
// /api/next/<id> (worker/index.ts) while the page is visible; shows nothing when the service
// is off, over quota, offline or has no departure for this station.
import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/components/I18n";
import { LineBadge } from "@/components/LineBadge";
import { isAnswer, minutesUntil, stillAhead, type DepartureRow } from "@/lib/departures";
import { useOnline } from "@/lib/online";
import type { Line } from "@/lib/types";
import styles from "./departures.module.css";

const REFRESH_MS = 30_000; // same as the Worker's cache
const TICK_MS = 10_000; // the minutes are recounted between two refreshes
const SHORT = 4; // rows shown before "show all"

interface Loaded {
  rows: DepartureRow[];
  /** Server clock minus device clock, so a wrong device clock does not shift the minutes. */
  skew: number;
}

export function NextDepartures({
  placeId,
  lines,
  onRows,
}: {
  placeId: string;
  lines: Line[];
  /** Number of rows drawn, so the screen can lay out what is under the block again. */
  onRows?: (n: number) => void;
}) {
  const { t } = useI18n();
  const ts = t.station;
  const online = useOnline();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [nowMs, setNowMs] = useState(0);
  const [all, setAll] = useState(false);

  useEffect(() => {
    if (!online) return;
    let stopped = false;
    let timer = 0;
    const load = async () => {
      window.clearTimeout(timer);
      if (document.visibilityState !== "visible") return;
      try {
        const res = await fetch(`/api/next/${encodeURIComponent(placeId)}`, { cache: "no-store" });
        const body: unknown = res.ok ? await res.json() : null;
        if (stopped) return;
        if (isAnswer(body) && body.status === "ok") {
          setLoaded({ rows: body.rows, skew: Date.parse(body.now) - Date.now() });
          setNowMs(Date.now());
        } else {
          setLoaded(null);
        }
      } catch {
        if (!stopped) setLoaded(null);
      }
      if (!stopped) timer = window.setTimeout(load, REFRESH_MS);
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    void load();
    const tick = window.setInterval(() => setNowMs(Date.now()), TICK_MS);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.clearInterval(tick);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [placeId, online]);

  const byId = useMemo(() => new Map(lines.map((l) => [l.id, l])), [lines]);
  const serverNow = loaded ? nowMs + loaded.skew : 0;
  const rows = useMemo(
    () => (loaded && online ? stillAhead(loaded.rows, serverNow).filter((r) => byId.has(r.line)) : []),
    [loaded, online, serverNow, byId],
  );
  const shown = all ? rows : rows.slice(0, SHORT);

  useEffect(() => {
    onRows?.(shown.length);
  }, [onRows, shown.length]);

  if (!rows.length) return null;
  const wait = (iso: string, atStop: boolean) => {
    const m = minutesUntil(iso, serverNow);
    if (m == null) return "";
    if (m === 0) return atStop ? ts.atPlatform : ts.approaching;
    return ts.minutes(m);
  };
  return (
    <section className={styles.block} aria-label={ts.departuresTitle}>
      <h2 className={styles.title}>{ts.departuresTitle}</h2>
      <ul className={styles.list}>
        {shown.map((r) => (
          <li key={`${r.line}|${r.dest}`} className={styles.row}>
            <LineBadge line={byId.get(r.line) as Line} />
            <span className={styles.dest}>{r.dest}</span>
            <span className={styles.times}>
              <strong>{wait(r.times[0], r.atStop)}</strong>
              {r.times[1] ? <span className={styles.then}>{wait(r.times[1], false)}</span> : null}
            </span>
          </li>
        ))}
      </ul>
      {rows.length > SHORT ? (
        <button type="button" className={styles.more} onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? ts.departuresLess : ts.departuresAll(rows.length)}
        </button>
      ) : null}
    </section>
  );
}
