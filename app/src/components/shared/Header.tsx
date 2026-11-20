"use client";

import Link from "next/link";
import { useEffect } from "react";
import { LangSwitch, useI18n } from "@/components/I18n";

/** The rabbit mark, drawn in the current ink colour (one cached file, used as a mask). */
export function RabbitMark({ height, className }: { height?: number; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`rabbit${className ? ` ${className}` : ""}`}
      style={height ? { height } : undefined}
    />
  );
}

/** Header row: rabbit mark (links home) on the left, the screen's controls on the right.
 *  The language switch always closes the row. */
export function Header({ children }: { children?: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <header className="hdr">
      {/* A plain link: going home is a full page load, which works the same in every browser
          and in the installed app. */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a href="/" className="hdr-home" aria-label={t.common.homeLabel}>
        <RabbitMark />
        <span className="hdr-name" aria-hidden="true">
          {t.common.appName}
        </span>
      </a>
      <div className="hdr-right">
        {children}
        <LangSwitch />
      </div>
    </header>
  );
}

export function MethodLink({ className }: { className?: string }) {
  const { t } = useI18n();
  return (
    <Link href="/a-propos/" className={`hdr-link${className ? ` ${className}` : ""}`}>
      {t.common.method}
    </Link>
  );
}

/** Station name with a chevron: goes to the home search (focus lands in the field). */
export function StationPicker({ name }: { name: string }) {
  const { t } = useI18n();
  return (
    <Link href="/#recherche" className="hdr-station" aria-label={`${name}. ${t.common.changeStation}`}>
      <span className="hdr-station-name">{name}</span>
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 9l6 6 6-6" />
      </svg>
    </Link>
  );
}

export function CloseLink({ href = "/" }: { href?: string }) {
  const { t } = useI18n();
  return (
    <Link href={href} className="hdr-link hdr-close">
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 6L6 18" />
        <path d="M6 6l12 12" />
      </svg>
      {t.common.close}
    </Link>
  );
}

const GROUND_COLOR = { signal: "#D9F84A", nuit: "#0E1116", papier: "#F6F7F4" } as const;

/** Keeps the browser chrome (theme-color) on the screen's ground. */
export function useThemeColor(ground: keyof typeof GROUND_COLOR) {
  useEffect(() => {
    let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = "theme-color";
      document.head.appendChild(meta);
    }
    meta.content = GROUND_COLOR[ground];
  }, [ground]);
}

/** A full-bleed screen on one of the three grounds, with its decorative light patches. */
export function Screen({
  ground,
  className,
  children,
}: {
  ground: keyof typeof GROUND_COLOR;
  className?: string;
  children: React.ReactNode;
}) {
  useThemeColor(ground);
  return (
    <div className={`screen ground-${ground}${className ? ` ${className}` : ""}`}>
      <span aria-hidden="true" className="patch patch-a" />
      <span aria-hidden="true" className="patch patch-b" />
      {children}
    </div>
  );
}
