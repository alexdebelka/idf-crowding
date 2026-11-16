"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "./I18n";
import { LineBadges } from "./LineBadge";
import { defaultDayType, formatInt, hh, hourRange, roundEntries, shownHours } from "@/lib/format";
import { formatDate } from "@/lib/i18n";
import { BANDS, DAY_TYPES, type DayTypeCode, type HourRow, type PlaceFile } from "@/lib/types";

export function PlaceView({ data }: { data: PlaceFile }) {
  const { t, lang } = useI18n();
  const available = DAY_TYPES.filter((d) => data.day_types[d]);
  const [dt, setDt] = useState<DayTypeCode>(available[0]);

  useEffect(() => {
    const guess = defaultDayType(new Date());
    // eslint-disable-next-line react-hooks/set-state-in-effect -- pick today's day type after load
    if (data.day_types[guess]) setDt(guess);
  }, [data]);

  const day = data.day_types[dt]!;
  const yMax = useMemo(() => {
    const all = available.flatMap((d) => shownHours(data.day_types[d]!.hours).map((h) => h.score));
    return Math.max(120, Math.ceil(Math.max(...all) / 20) * 20);
  }, [data, available]);
  const byHour = new Map(day.hours.map((h) => [h.h, h]));

  const hints = day.best_slots.around_peaks
    .map(({ peak, alternative }) => {
      const p = byHour.get(peak)!;
      const a = byHour.get(alternative)!;
      const pct = p.expected_entries > 0 ? Math.round(100 * (1 - a.expected_entries / p.expected_entries)) : 0;
      return { peak, alternative, pct };
    })
    .filter((x) => x.pct >= 10 && (byHour.get(x.peak)?.score ?? 0) >= 40);

  return (
    <article className="place">
      <Link href="/" className="back">
        {t.back}
      </Link>
      <header className="place-head">
        <h1>{data.place.name}</h1>
        <p className="muted">{data.place.town}</p>
        <LineBadges lines={data.place.lines} />
      </header>

      <section className="card" aria-labelledby="hourly-title">
        <div className="card-head">
          <h2 id="hourly-title">{t.hourly}</h2>
          <DayTypeTabs value={dt} options={available} onChange={setDt} />
        </div>

        <ul className="callouts">
          {hints.map((h) => (
            <li key={h.peak} className="callout">
              <span className="callout-icon" aria-hidden="true">↺</span>
              {t.peakHint(hh(h.peak), hh(h.alternative), h.pct)}
            </li>
          ))}
          {day.best_slots.quietest.length > 0 && (
            <li className="callout">
              <span className="callout-icon" aria-hidden="true">◎</span>
              {t.quietest(day.best_slots.quietest.map(hh).join(", "))}
            </li>
          )}
        </ul>
        {day.low_confidence && <p className="warn">{t.lowConfidence}</p>}

        <HourChart rows={shownHours(day.hours)} yMax={yMax} quietest={day.best_slots.quietest} />
        <Legend withReference />
        <p className="muted small">
          {t.dailyEntries(formatInt(roundEntries(day.daily_entries), lang))} ({t.entriesNote}).{" "}
          {t.basedOn(day.n_days, formatDate(data.data_period.start, lang), formatDate(data.data_period.end, lang))}
        </p>
        <details className="table-view">
          <summary>{t.showTable}</summary>
          <table>
            <thead>
              <tr>
                <th scope="col">{t.hour}</th>
                <th scope="col">{t.score}</th>
                <th scope="col">{t.band}</th>
                <th scope="col">{t.entries}</th>
              </tr>
            </thead>
            <tbody>
              {shownHours(day.hours).map((r) => (
                <tr key={r.h}>
                  <td>{hourRange(r.h)}</td>
                  <td className="num">{r.score}</td>
                  <td>{t.bands[r.band]}</td>
                  <td className="num">≈ {formatInt(roundEntries(r.expected_entries), lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

      <section className="card" aria-labelledby="week-title">
        <div className="card-head">
          <h2 id="week-title">{t.typicalWeek}</h2>
        </div>
        <p className="muted small">{t.typicalWeekHelp}</p>
        <WeekHeatmap data={data} selected={dt} onSelect={setDt} />
        <Legend />
      </section>

      <p className="muted small note">{t.notTrainLoad}</p>
    </article>
  );
}

function DayTypeTabs({
  value,
  options,
  onChange,
}: {
  value: DayTypeCode;
  options: DayTypeCode[];
  onChange: (d: DayTypeCode) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="tabs" role="radiogroup" aria-label={t.typicalWeek}>
      {options.map((d) => (
        <button
          key={d}
          type="button"
          role="radio"
          aria-checked={d === value}
          className={d === value ? "on" : ""}
          onClick={() => onChange(d)}
          title={t.dayTypes[d]}
        >
          <span className="long">{t.dayTypes[d]}</span>
          <span className="short">{t.dayTypesShort[d]}</span>
        </button>
      ))}
    </div>
  );
}

export function Legend({ withReference = false }: { withReference?: boolean }) {
  const { t } = useI18n();
  return (
    <ul className="legend" aria-label={t.band}>
      {BANDS.map((b, i) => (
        <li key={b}>
          <span className={`swatch band-${b}`} aria-hidden="true" />
          {t.bands[b]}{" "}
          <span className="muted">
            {["< 40", "40–69", "70–99", "≥ 100"][i]}
          </span>
        </li>
      ))}
      {withReference && (
        <li>
          <span className="ref-swatch" aria-hidden="true" />
          {t.referenceLine}
        </li>
      )}
      {withReference && (
        <li>
          <span className="quiet-swatch" aria-hidden="true" />
          {t.quietLegend}
        </li>
      )}
    </ul>
  );
}

const H = 250;
const M = { top: 14, right: 8, bottom: 30, left: 34 };

/** Chart width follows its container so axis text keeps its real size on phones. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(300, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function HourChart({ rows, yMax, quietest }: { rows: HourRow[]; yMax: number; quietest: number[] }) {
  const { t, lang } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const [ref, W] = useWidth(680);
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const step = iw / rows.length;
  const bw = Math.max(4, Math.min(step - (step > 20 ? 4 : 2), 26));
  const labelEvery = step < 18 ? 2 : 1;
  const y = (v: number) => M.top + ih - (Math.min(v, yMax) / yMax) * ih;
  const ticks = [0, 50, 100, 150, 200, 250, 300].filter((v) => v <= yMax);
  const hv = hover === null ? null : rows[hover];

  return (
    <div className="chart" ref={ref} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t.hourly}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} className={v === 100 ? "ref" : "grid"} />
            <text x={M.left - 6} y={y(v) + 4} className="axis" textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const x = M.left + i * step + (step - bw) / 2;
          const top = y(r.score);
          const h = Math.max(M.top + ih - top, r.score > 0 ? 2 : 0);
          const rad = Math.min(4, h, bw / 2);
          const yb = M.top + ih;
          const d =
            h <= 0
              ? ""
              : `M${x},${yb} V${yb - h + rad} Q${x},${yb - h} ${x + rad},${yb - h} H${x + bw - rad} Q${x + bw},${yb - h} ${x + bw},${yb - h + rad} V${yb} Z`;
          const isQuiet = quietest.includes(r.h);
          return (
            <g key={r.h} className={hover === i ? "bar hover" : "bar"}>
              {d && <path d={d} className={`band-${r.band}`} />}
              {isQuiet && <circle cx={x + bw / 2} cy={yb + 22} r={3} className="quiet-dot" />}
              {(i % labelEvery === 0 || isQuiet) && (
                <text x={x + bw / 2} y={yb + 14} className={isQuiet ? "axis strong" : "axis"} textAnchor="middle">
                  {r.h}
                </text>
              )}
              <rect
                x={M.left + i * step}
                y={M.top}
                width={step}
                height={ih + M.bottom}
                fill="transparent"
                tabIndex={0}
                aria-label={`${hourRange(r.h)}: ${t.score} ${r.score}, ${t.bands[r.band]}`}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
              />
            </g>
          );
        })}
      </svg>
      {hv && hover !== null && (
        <div
          className="tip"
          style={{
            left: `${((M.left + hover * step + step / 2) / W) * 100}%`,
            top: `${(y(hv.score) / H) * 100}%`,
          }}
          role="status"
        >
          <strong>{hourRange(hv.h)}</strong>
          <span>
            <span className={`swatch band-${hv.band}`} aria-hidden="true" /> {t.bands[hv.band]} · {t.score}{" "}
            {hv.score}
          </span>
          <span className="muted">{t.expectedEntries(formatInt(roundEntries(hv.expected_entries), lang))}</span>
        </div>
      )}
    </div>
  );
}

function WeekHeatmap({
  data,
  selected,
  onSelect,
}: {
  data: PlaceFile;
  selected: DayTypeCode;
  onSelect: (d: DayTypeCode) => void;
}) {
  const { t, lang } = useI18n();
  const types = DAY_TYPES.filter((d) => data.day_types[d]);
  const hours = shownHours(data.day_types[types[0]]!.hours).map((h) => h.h);
  return (
    <div className="heat-scroll">
      <table className="heat">
        <thead>
          <tr>
            <th scope="col" className="sr-only-cell">
              <span className="sr-only">{t.typicalWeek}</span>
            </th>
            {hours.map((h) => (
              <th key={h} scope="col" className="hcol">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {types.map((d) => {
            const day = data.day_types[d]!;
            const rows = new Map(day.hours.map((r) => [r.h, r]));
            return (
              <tr key={d} className={d === selected ? "sel" : ""} onClick={() => onSelect(d)}>
                <th scope="row">
                  <button type="button" onClick={() => onSelect(d)} aria-pressed={d === selected}>
                    <span className="long">{t.dayTypes[d]}</span>
                    <span className="short">{t.dayTypesShort[d]}</span>
                  </button>
                </th>
                {hours.map((h) => {
                  const r = rows.get(h)!;
                  return (
                    <td
                      key={h}
                      className={`cell band-${r.band}`}
                      title={`${t.dayTypes[d]} · ${hourRange(h)} · ${t.score} ${r.score} (${t.bands[r.band]}) · ${t.expectedEntries(formatInt(roundEntries(r.expected_entries), lang))}`}
                    >
                      {r.score}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
