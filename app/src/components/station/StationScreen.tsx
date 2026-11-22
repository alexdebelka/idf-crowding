"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/components/I18n";
import { LineBadges } from "@/components/LineBadge";
import { BarChart, HoursTable, Legend } from "@/components/shared/BarChart";
import { Header, MethodLink, Screen, StationPicker } from "@/components/shared/Header";
import { seedOf } from "@/lib/crowd";
import { formatDate, formatDayLong, formatDayShort, formatPct } from "@/lib/i18n";
import { touchSaved } from "@/lib/saved";
import { FavouriteButton } from "./FavouriteButton";
import {
  dayComparison,
  dayCalmest,
  dayHeadline,
  dayReason,
  isSpecialDay,
  nowSummary,
} from "@/lib/sentences";
import {
  bandOf,
  chartHours,
  dayFacts,
  dayView,
  nowFacts,
  upcomingDates,
  type BandRule,
  type DayFacts,
  type DayView,
  type NowFacts,
} from "@/lib/state";
import { CHART_HOURS, serviceNow } from "@/lib/time";
import type { PlaceFile } from "@/lib/types";
import { BackLayer, CrowdBand } from "./Crowd";
import { DatePill, TodayButton } from "./DatePill";
import { NextDepartures } from "./NextDepartures";
import {
  calmScene,
  chosenDate,
  COMPUTER_FULL_OVERLAP,
  dateParam,
  dayMarks,
  fullScene,
  layoutOf,
  legendFor,
  nb,
  nowMarks,
  nowVariant,
  pickerRange,
  scrollToHour,
  shownAccuracy,
  withDate,
  type Layout,
} from "./logic";
import styles from "./station.module.css";

/** What only the device knows: the clock, the URL query and the screen width. */
interface Env {
  nowMs: number;
  search: string;
  width: number;
}

type Mode =
  | { kind: "now"; today: string; view: DayView; facts: NowFacts }
  | { kind: "date"; today: string; date: string; view: DayView; facts: DayFacts }
  | { kind: "empty"; today: string };

const readEnv = (): Env => ({
  nowMs: Date.now(),
  search: window.location.search,
  width: document.documentElement.clientWidth || window.innerWidth,
});

export function StationScreen({ data, bands }: { data: PlaceFile; bands: BandRule[] }) {
  const { t, lang } = useI18n();
  const ts = t.station;
  const tc = t.common;
  const place = data.place;
  // Static HTML is rendered before any clock is known: `env` stays null for the first paint
  // (station name and badges only), then the device's Paris time decides the state.
  const [env, setEnv] = useState<Env | null>(null);

  useEffect(() => {
    touchSaved({ id: place.id, name: place.name });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read the device once mounted
    setEnv(readEnv());
    let timer = 0;
    const schedule = () => {
      // Paris hours start on UTC hour boundaries: refresh just after the next one.
      const wait = 3_600_000 - (Date.now() % 3_600_000) + 1_000;
      timer = window.setTimeout(() => {
        setEnv(readEnv());
        schedule();
      }, wait);
    };
    schedule();
    let raf = 0;
    const onResize = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setEnv((e) => (e ? { ...e, width: readEnv().width } : e)));
    };
    const onPop = () => setEnv(readEnv());
    const onVisible = () => {
      if (document.visibilityState === "visible") setEnv(readEnv());
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("popstate", onPop);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearTimeout(timer);
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("popstate", onPop);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [place.id, place.name]);

  const available = useMemo(
    () => (data.forecast?.dates ?? []).map((d) => d.d),
    [data.forecast],
  );

  const mode: Mode | null = useMemo(() => {
    if (!env) return null;
    const sn = serviceNow(new Date(env.nowMs));
    const ahead = upcomingDates(data, sn.date).map((d) => d.d);
    const date = chosenDate(dateParam(env.search), sn.date, ahead);
    if (date) {
      const view = dayView(data, date);
      if (view) return { kind: "date", today: sn.date, date, view, facts: dayFacts(view.scores) };
    }
    const view = dayView(data, sn.date);
    if (!view) return { kind: "empty", today: sn.date };
    return { kind: "now", today: sn.date, view, facts: nowFacts(view.scores, sn.hour, bands) };
  }, [env, data, bands]);

  // A "?d=" that does not name a forecast date ahead (past, malformed) shows "now": clean the URL.
  useEffect(() => {
    if (!env || !mode || mode.kind === "date") return;
    if (dateParam(env.search) != null) {
      window.history.replaceState(window.history.state, "", window.location.pathname + withDate(env.search, null));
    }
  }, [env, mode]);

  const go = useCallback((date: string | null) => {
    const url = window.location.pathname + withDate(window.location.search, date);
    window.history.pushState(window.history.state, "", url);
    setEnv(readEnv());
    window.scrollTo(0, 0);
  }, []);

  const layout: Layout = env ? layoutOf(env.width) : "phone";
  const today = mode?.today ?? "";
  const range = mode ? pickerRange(today, available) : null;
  const chosen = mode?.kind === "date" ? mode.date : null;
  const shown = chosen ? cap(formatDayShort(chosen, lang)) : tc.today;
  const pill = range ? (
    <DatePill
      label={shown}
      accessibleLabel={ts.pickerLabel(chosen ? formatDayLong(chosen, lang) : tc.today.toLowerCase())}
      value={chosen ?? today}
      min={range.min}
      max={range.max}
      onPick={(d) => go(chosenDate(d, today, available))}
    />
  ) : null;
  const back = chosen ? (
    <TodayButton label={ts.backToToday} accessibleLabel={ts.backToTodayLabel} onClick={() => go(null)} />
  ) : null;

  const ground = !mode || mode.kind === "empty" ? "papier" : mode.kind === "date" ? "papier" : mode.facts.ground;
  const accuracy = shownAccuracy(data);
  const accuracyText = accuracy ? tc.stationAccuracy(formatPct(accuracy.wape_pct, lang)) : null;

  return (
    <Screen ground={ground} className={styles.screen}>
      <div className={`${styles.page} ${mode ? styles[`mode-${mode.kind === "now" ? mode.facts.ground : mode.kind}`] : ""}`}>
        <Header>
          <StationPicker name={place.name} />
          <FavouriteButton place={{ id: place.id, name: place.name }} />
          {layout !== "phone" ? pill : null}
          {layout === "computer" ? back : null}
          <MethodLink className={styles.notPhone} />
        </Header>
        <div className={styles.badgesRow}>
          <LineBadges lines={place.lines} label={tc.lines} />
        </div>
        {layout === "phone" && pill ? (
          <div className={styles.pillRow}>
            {pill}
            {back}
          </div>
        ) : null}
        {!mode ? (
          <h1 className="sr-only">{place.name}</h1>
        ) : mode.kind === "empty" ? (
          <p className={styles.emptyNote}>{tc.dayNoData}</p>
        ) : mode.kind === "now" ? (
          <NowView
            data={data}
            mode={mode}
            bands={bands}
            layout={layout}
            width={env?.width ?? 390}
            accuracyText={accuracyText}
          />
        ) : (
          <DateView data={data} mode={mode} bands={bands} layout={layout} back={layout === "tablet" ? back : null} accuracyText={accuracyText} />
        )}
      </div>
    </Screen>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "Jeudi 24 décembre" or "Jeudi 24 décembre, veille de Noël". */
function useDayLine(date: string, entry: DayView["entry"]) {
  const { t, lang } = useI18n();
  const day = formatDayLong(date, lang);
  const reason = dayReason(t.common, entry);
  return reason ? t.station.dayWithReason(day, reason) : day;
}

function useHoursTable(scores: number[], bands: BandRule[]) {
  const { t } = useI18n();
  const tc = t.common;
  return (
    <HoursTable
      hours={chartHours(scores)}
      caption={tc.tableCaption}
      headers={[tc.tableHour, tc.tableScore, tc.tableBand]}
      hourLabel={tc.hour}
      bandLabel={(s) => tc.band[bandOf(s, bands)]}
    />
  );
}

function NowView({
  data,
  mode,
  bands,
  layout,
  width,
  accuracyText,
}: {
  data: PlaceFile;
  mode: Extract<Mode, { kind: "now" }>;
  bands: BandRule[];
  layout: Layout;
  width: number;
  accuracyText: string | null;
}) {
  const { t } = useI18n();
  const tc = t.common;
  const ts = t.station;
  const f = mode.facts;
  const calm = f.ground === "signal";
  const hours = chartHours(mode.view.scores);
  const marks = nowMarks(f);
  const variant = nowVariant(f);
  const dayLine = useDayLine(mode.today, mode.view.entry);
  const comparison = dayComparison(tc, mode.view.entry);
  const table = useHoursTable(mode.view.scores, bands);
  const scroller = useRef<HTMLDivElement>(null);

  // Phone: the chart opens on the current hour.
  useEffect(() => {
    const el = scroller.current;
    if (el && layout === "phone") el.scrollLeft = scrollToHour(f.hour, CHART_HOURS);
  }, [f.hour, layout]);

  // Phone and tablet: the crowd fills the height left under the content (measured once laid out).
  const slot = useRef<HTMLDivElement>(null);
  const [space, setSpace] = useState<number | undefined>(undefined);
  // Rows of the real-time block: it loads after the first layout and changes the height above the crowd.
  const [departureRows, setDepartureRows] = useState(0);
  const { lang } = useI18n();
  useLayoutEffect(() => {
    const el = slot.current;
    if (!el || layout === "computer") return;
    const top = el.getBoundingClientRect().top + window.scrollY;
    setSpace(Math.round(window.innerHeight - top));
  }, [layout, width, lang, f.band, f.hour, accuracyText, departureRows]);

  const seed = seedOf(`${data.place.id}:${f.band}:${layout}`);
  const scene = useMemo(
    () => (calm ? calmScene(layout, f.band, width, seed, space) : null),
    [calm, layout, f.band, width, seed, space],
  );
  const full = useMemo(
    () => (calm ? null : fullScene(layout, f.band === "busy" ? "busy" : "very_busy", width, seed, space)),
    [calm, layout, f.band, width, seed, space],
  );

  const chart = (
    <BarChart
      hours={hours}
      marks={marks}
      variant={variant}
      label={layout === "phone" ? `${tc.chartLabel} ${tc.chartScrollHint}` : tc.chartLabel}
      hourLabel={tc.hourShort}
      scrollRef={scroller}
    />
  );
  const legend = <Legend items={legendFor(marks, tc)} variant={variant} />;
  // Phone mockups have no link to the method page: the note line carries it there.
  const note =
    layout === "phone" || accuracyText ? (
      <p className={styles.nowNote}>
        {accuracyText ? <>{nb(accuracyText)} </> : null}
        <Link href="/a-propos/">{tc.howComputed}</Link>
      </p>
    ) : null;
  // One-word headlines ("Calme.", "Chargé.") take the large size; two-word ones ("Assez calme.",
  // "Très chargé.") the smaller one, so they keep the line count of the mockups.
  const long = f.band === "moderate" || f.band === "very_busy";
  const headline = (
    <h1 className={`${styles.headline} ${long ? styles.headlineLong : styles.headlineShort}`}>
      <span className="sr-only">{ts.stationPrefix(data.place.name)}</span>
      {tc.headline[f.band]}
    </h1>
  );
  const summary = <p className={styles.summary}>{nb(nowSummary(tc, f))}</p>;
  const departures = <NextDepartures placeId={data.place.id} lines={data.place.lines} onRows={setDepartureRows} />;
  const crowd = calm
    ? scene && <CrowdBand layer={scene.front} tone="calm" id="front" rabbit={scene.rabbit} />
    : full && <CrowdBand layer={full} tone="night" id="crowd" className={layout === "computer" ? styles.bandBehind : undefined} />;

  if (layout === "computer") {
    return (
      <>
        <div className={`${styles.headBlock} ${styles.headRow}`}>
          {headline}
          {note}
        </div>
        <div className={styles.summaryBlock}>{summary}</div>
        <div className={styles.dateRow}>
          <p className={styles.dateLine}>{ts.byHour(dayLine)}</p>
          {comparison ? <p className={styles.comparison}>{nb(comparison)}</p> : null}
          {legend}
        </div>
        <div className={styles.stage}>
          {scene?.back ? <BackLayer layer={scene.back} id="back" /> : null}
          {chart}
        </div>
        {departures}
        {table}
        <div style={{ marginTop: calm ? 6 : -COMPUTER_FULL_OVERLAP }} className={styles.bandWrap}>
          {crowd}
        </div>
      </>
    );
  }
  if (layout === "tablet") {
    return (
      <>
        <div className={styles.headBlock}>
          {headline}
          {summary}
        </div>
        <div className={styles.chartBlock}>
          <p className={styles.dateLine}>{dayLine}</p>
          {chart}
          {legend}
          {comparison ? <p className={styles.comparison}>{nb(comparison)}</p> : null}
          {note}
          {departures}
        </div>
        {table}
        <div ref={slot} className={styles.bandSlot}>
          {crowd}
        </div>
      </>
    );
  }
  return (
    <>
      <div className={styles.headBlock}>
        {headline}
        {summary}
      </div>
      {chart}
      <div className={styles.legendBlock}>
        {legend}
        {note}
        {departures}
      </div>
      {table}
      <div ref={slot} className={styles.bandSlot}>
        {crowd}
      </div>
    </>
  );
}

function DateView({
  data,
  mode,
  bands,
  layout,
  back,
  accuracyText,
}: {
  data: PlaceFile;
  mode: Extract<Mode, { kind: "date" }>;
  bands: BandRule[];
  layout: Layout;
  back: React.ReactNode;
  accuracyText: string | null;
}) {
  const { t, lang } = useI18n();
  const tc = t.common;
  const ts = t.station;
  const f = mode.facts;
  const entry = mode.view.entry;
  const marks = dayMarks(f);
  const dayLine = useDayLine(mode.date, entry);
  const calmest = dayCalmest(tc, f);
  const comparison = dayComparison(tc, entry);
  const table = useHoursTable(mode.view.scores, bands);
  const dataEnd = data.forecast?.data_end ?? data.data_period.end;

  const headline = (
    <h1 className={styles.headline}>
      <span className="sr-only">{ts.stationPrefix(data.place.name)}</span>
      {nb(dayHeadline(tc, f))}
    </h1>
  );
  const chart = (
    <div className={styles.dayChart}>
      <BarChart
        hours={chartHours(mode.view.scores)}
        marks={marks}
        variant="date"
        label={`${dayLine}. ${layout === "phone" ? `${tc.chartLabel} ${tc.chartScrollHint}` : tc.chartLabel}`}
        hourLabel={tc.hourShort}
      />
    </div>
  );
  const legend = <Legend items={legendFor(marks, tc)} variant="date" />;
  const footer = (
    <p className={styles.footer}>
      {tc.dataUntil(formatDate(dataEnd, lang))}{" "}
      {isSpecialDay(entry) ? <>{tc.specialDayNote} </> : null}
      {mode.view.source === "typical" ? <>{tc.typicalNote} </> : null}
      {accuracyText ? <>{nb(accuracyText)} </> : null}
      <Link href="/a-propos/">{tc.howComputed}</Link>
    </p>
  );
  const facts = nb([calmest, comparison].filter(Boolean).join(" "));

  if (layout === "computer") {
    return (
      <>
        <div className={styles.headBlock}>{headline}</div>
        <div className={styles.summaryBlock}>{calmest ? <p className={styles.summary}>{nb(calmest)}</p> : null}</div>
        <div className={styles.dateRow}>
          <p className={styles.dateLine}>{ts.byHour(dayLine)}</p>
          {comparison ? <p className={styles.comparison}>{nb(comparison)}</p> : null}
          {legend}
        </div>
        {chart}
        {table}
        {footer}
      </>
    );
  }
  if (layout === "tablet") {
    return (
      <>
        <div className={styles.headBlock}>
          <div className={styles.dateLineRow}>
            <p className={styles.dateLine}>{dayLine}</p>
            {back}
          </div>
          {headline}
          {facts ? <p className={styles.summary}>{facts}</p> : null}
        </div>
        <div className={styles.chartBlock}>
          {chart}
          {legend}
        </div>
        {table}
        {footer}
      </>
    );
  }
  return (
    <>
      <div className={styles.headBlock}>
        <p className={styles.dateLine}>{dayLine}</p>
        {headline}
      </div>
      {chart}
      <div className={styles.legendBlock}>{legend}</div>
      {facts ? <p className={styles.facts}>{facts}</p> : null}
      {table}
      {footer}
    </>
  );
}
