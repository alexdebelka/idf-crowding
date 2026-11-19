"use client";

import { useI18n } from "@/components/I18n";
import { CloseLink, Header, Screen } from "@/components/shared/Header";
import {
  type AccuracyFile,
  type BandRange,
  type ForecastWindow,
  type Tile,
  accuracySpread,
  accuracyTiles,
  backtestLagMonths,
} from "@/lib/accuracy";
import { formatDate, formatPct, type Lang } from "@/lib/i18n";
import type { Period } from "@/lib/types";
import s from "./method.module.css";

const NIGHT = new Set(["busy", "very_busy"]);

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className={s.section} aria-labelledby={id}>
      <h2 id={id} className={s.h2}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function rangeText(r: BandRange, lang: Lang, t: ReturnType<typeof useI18n>["t"]["method"]) {
  const n = (x: number) => formatPct(x, lang);
  if (r.from == null && r.below != null) return t.below(n(r.below));
  if (r.from != null && r.below == null) return t.andAbove(n(r.from));
  if (r.from != null && r.below != null) return t.between(n(r.from), n(r.below));
  return "";
}

function TileView({ tile }: { tile: Tile }) {
  const { t, lang } = useI18n();
  const m = t.method;
  const [value, label] =
    tile.kind === "station"
      ? [m.about(formatPct(tile.pct, lang)), m.tileStation]
      : tile.kind === "network"
        ? [m.about(formatPct(tile.pct, lang)), m.tileNetwork]
        : tile.kind === "band"
          ? [m.tileBandValue(tile.inTen), m.tileBand]
          : [m.about(formatPct(tile.pct, lang)), m.tileSpecial(tile.season)];
  return (
    <li className={s.tile}>
      <span className={s.tileValue}>{value}</span>
      <span className={s.tileLabel}>{label}</span>
    </li>
  );
}

export interface MethodPageProps {
  bands: BandRange[];
  dataPeriod: Period;
  accuracy: AccuracyFile | null;
  forecast: ForecastWindow | null;
}

/** /a-propos/: how the forecast is made, how accurate it is, and its limits (Method artboard). */
export function MethodPage({ bands, dataPeriod, accuracy, forecast }: MethodPageProps) {
  const { t, lang } = useI18n();
  const m = t.method;
  const date = (iso: string) => formatDate(iso, lang);
  const tiles = accuracyTiles(accuracy);
  const spread = accuracySpread(accuracy);
  const lag = backtestLagMonths(accuracy);
  const special = accuracy?.tiles.special_days;

  return (
    <Screen ground="papier" className={s.screen}>
      <div className={s.top}>
        <Header>
          <CloseLink />
        </Header>
      </div>
      <main className={s.column}>
        <div className={s.intro}>
          <h1 className={s.h1}>{m.headline}</h1>
          <p className={s.lead}>{m.lead}</p>
        </div>

        <Section id="m-counted" title={m.countedTitle}>
          <p>{m.counted}</p>
          <p>{m.notCounted}</p>
        </Section>

        <Section id="m-levels" title={m.levelsTitle}>
          <p>{m.levels(date(dataPeriod.start), date(dataPeriod.end))}</p>
          {bands.length > 0 && (
            <ul className={s.bands}>
              {bands.map((r) => (
                <li key={r.band} className={`${s.bandRow} ${NIGHT.has(r.band) ? s.bandNight : ""}`}>
                  <span className={s.bandName}>{t.common.band[r.band]}</span>
                  <span className={s.bandRange}>{rangeText(r, lang, m)}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section id="m-forecast" title={m.forecastTitle}>
          <p>{m.forecastModels}</p>
          <p>{m.forecastHours}</p>
        </Section>

        {accuracy && (
          <Section id="m-accuracy" title={m.accuracyTitle}>
            <p>
              {lag
                ? m.accuracyHow(
                    date(accuracy.log.period.start),
                    date(accuracy.log.period.end),
                    String(lag.min),
                    String(lag.max),
                  )
                : m.accuracyHowShort(
                    date(accuracy.log.period.start),
                    date(accuracy.log.period.end),
                  )}{" "}
              {m.accuracyCaveats}
            </p>
            {tiles.length > 0 && (
              <ul className={s.tiles}>
                {tiles.map((tile) => (
                  <TileView key={tile.kind} tile={tile} />
                ))}
              </ul>
            )}
            {spread && (
              <>
                <p className={s.spread}>
                  {m.spread(formatPct(spread.median, lang), formatPct(spread.p90, lang))}
                </p>
                <p className={s.note}>{m.spreadBase(spread.n, spread.total, spread.minDays)}</p>
              </>
            )}
          </Section>
        )}

        <Section id="m-delay" title={m.delayTitle}>
          <p>
            {forecast
              ? m.delay(
                  date(forecast.dataEnd),
                  date(forecast.issueDate),
                  String(forecast.minMonths),
                  String(forecast.maxMonths),
                )
              : m.delayNoForecast(date(dataPeriod.end))}
          </p>
        </Section>

        <Section id="m-limits" title={m.limitsTitle}>
          <p>{m.limitsEvents}</p>
          <p>{special ? m.limitsSpecial(special.season) : m.limitsSpecialShort}</p>
          <p>{m.limitsTrend}</p>
        </Section>

        <footer className={s.footer}>
          <p>{t.common.attribution}</p>
          <p className={s.muted}>{t.common.independent}</p>
          <p className={s.muted}>
            {t.common.promise} {m.traffic}
          </p>
        </footer>
      </main>
    </Screen>
  );
}
