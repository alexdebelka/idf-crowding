"use client";

import { useI18n } from "./I18n";

export function Hero({ count }: { count: number }) {
  const { t } = useI18n();
  return (
    <section className="hero">
      <h1>{t.tagline}</h1>
      <p className="muted">{t.stationsCount(count)}</p>
    </section>
  );
}
