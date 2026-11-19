"use client";

import { useEffect, useId, useRef } from "react";
import { useI18n } from "@/components/I18n";
import { RabbitMark } from "@/components/shared/Header";
import type { InstallMode } from "@/lib/install";
import s from "./home.module.css";

const DOWNLOAD = (
  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 4v11" />
    <path d="M7 11l5 5 5-5" />
    <path d="M5 20h14" />
  </svg>
);

export { DOWNLOAD as DownloadIcon };

/** Bottom sheet: lime "Installer", "Plus tard", iPhone hint. Closing by any way other than
 *  a finished install counts as "Plus tard". */
export function InstallSheet({
  mode,
  onInstall,
  onClose,
}: {
  mode: InstallMode;
  onInstall: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    primaryRef.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      before?.focus?.();
    };
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
    } else if (e.key === "Tab") {
      const items = sheetRef.current?.querySelectorAll<HTMLElement>("button");
      if (!items?.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  return (
    <div className={s.sheetLayer} onKeyDown={onKeyDown}>
      <div aria-hidden="true" className={s.scrim} onClick={onClose} />
      <div ref={sheetRef} role="dialog" aria-modal="true" aria-labelledby={titleId} className={s.sheet}>
        <span aria-hidden="true" className={s.sheetPatch} />
        <span aria-hidden="true" className={s.grab} />
        <div className={s.sheetHead}>
          <span aria-hidden="true" className={s.appIcon}>
            <RabbitMark height={46} />
          </span>
          <div className={s.sheetTitles}>
            <h2 id={titleId} className={s.sheetTitle}>
              {t.home.installTitle}
            </h2>
            <p className={s.sheetPromise}>{t.common.promise}</p>
          </div>
        </div>
        <p className={s.sheetBody}>{t.home.installBody}</p>
        <div className={s.sheetActions}>
          <button
            ref={primaryRef}
            type="button"
            className={s.limeBtn}
            onClick={mode === "prompt" ? onInstall : onClose}
          >
            {mode === "prompt" ? DOWNLOAD : null}
            {mode === "prompt" ? t.home.install : t.home.gotIt}
          </button>
          {mode === "prompt" ? (
            <button type="button" className={s.laterBtn} onClick={onClose}>
              {t.home.later}
            </button>
          ) : null}
        </div>
        <p className={mode === "ios" ? s.sheetHintOn : s.sheetHint}>{t.home.iosHint}</p>
      </div>
    </div>
  );
}
