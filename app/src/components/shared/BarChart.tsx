import type { ChartHour } from "@/lib/state";

export type BarMark = "now" | "calmer" | "busiest" | "calmest";
export type ChartVariant = "full" | "calm" | "date";

export interface LegendItem {
  mark: BarMark;
  label: string;
}

/** One bar per hour, 5 h to 0 h (design spec, section 6 "Bar chart"). Sizes come from CSS:
 *  the phone scrolls sideways, tablet and computer show the whole day. Set `--chart-h` on a
 *  parent to change the bar height. The bars are an image for assistive tech; `table` is the
 *  text alternative that goes with it. */
export function BarChart({
  hours,
  marks,
  variant,
  label,
  hourLabel,
  scrollRef,
}: {
  hours: ChartHour[];
  marks: Partial<Record<number, BarMark>>;
  variant: ChartVariant;
  label: string;
  hourLabel: (h: number) => string;
  scrollRef?: React.Ref<HTMLDivElement>;
}) {
  // "Now" charts share one scale (100 = the station's reference), so a calm day looks calm.
  // A chosen date is read for its shape: it fills the chart up to its own peak.
  const peak = Math.max(0, ...hours.map((x) => x.score));
  const top = variant === "date" ? Math.max(1, peak) : Math.max(100, peak);
  return (
    <div ref={scrollRef} className={`chart chart-${variant}`} role="img" aria-label={label} tabIndex={0}>
      {hours.map(({ h, score }) => {
        const mark = marks[h];
        return (
          <div key={h} className={`bar-col${mark ? ` is-${mark}` : ""}`} data-hour={h}>
            <span className="bar-area">
              <span className="bar" style={{ height: `${Math.max(3, (score / top) * 100)}%` }} />
            </span>
            <span className="bar-label">{hourLabel(h)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function Legend({ items, variant }: { items: LegendItem[]; variant: ChartVariant }) {
  return (
    <ul className={`legend chart-${variant}`}>
      {items.map((it) => (
        <li key={it.mark} className={`is-${it.mark}`}>
          <span aria-hidden="true" className="swatch" />
          {it.label}
        </li>
      ))}
    </ul>
  );
}

/** Hour-by-hour values for screen readers (kept from v0 as the chart's text alternative). */
export function HoursTable({
  hours,
  caption,
  headers,
  hourLabel,
  bandLabel,
}: {
  hours: ChartHour[];
  caption: string;
  headers: [string, string, string];
  hourLabel: (h: number) => string;
  bandLabel: (score: number) => string;
}) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          {headers.map((h) => (
            <th key={h} scope="col">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {hours.map(({ h, score }) => (
          <tr key={h}>
            <th scope="row">{hourLabel(h)}</th>
            <td>{score}</td>
            <td>{bandLabel(score)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
