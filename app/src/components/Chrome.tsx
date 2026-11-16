"use client";

import Link from "next/link";
import { LangToggle, useI18n } from "./I18n";
import { formatDate } from "@/lib/i18n";
import type { Attribution, Period } from "@/lib/types";

export function Header() {
  const { t } = useI18n();
  return (
    <header className="topbar">
      <div className="wrap topbar-in">
        <Link href="/" className="brand" aria-label={t.appName}>
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22">
              <rect x="3" y="15" width="3" height="6" rx="1" />
              <rect x="8.5" y="11" width="3" height="10" rx="1" />
              <rect x="14" y="6" width="3" height="15" rx="1" opacity=".45" />
              <rect x="19.5" y="13" width="3" height="8" rx="1" />
            </svg>
          </span>
          <span className="brand-name">{t.appName}</span>
        </Link>
        <nav className="nav">
          <Link href="/">{t.navStations}</Link>
          <Link href="/a-propos/">{t.navAbout}</Link>
          <LangToggle />
        </nav>
      </div>
    </header>
  );
}

export function Footer({ attribution, period }: { attribution: Attribution; period: Period }) {
  const { t, lang } = useI18n();
  return (
    <footer className="footer">
      <div className="wrap">
        <p>
          <a href={attribution.source_url} rel="noopener">
            {t.footerData}
          </a>{" "}
          · {t.dataPeriod(formatDate(period.start, lang), formatDate(period.end, lang))}
        </p>
        <p>
          <a href={attribution.license_url} rel="noopener">
            {t.footerDerived}
          </a>
        </p>
        <p className="muted">{t.footerIndependent}</p>
      </div>
    </footer>
  );
}
