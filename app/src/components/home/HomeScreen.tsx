"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/components/I18n";
import { Header, MethodLink, Screen } from "@/components/shared/Header";
import { shouldAutoOffer, useInstall } from "@/lib/install";
import { useOnline } from "@/lib/online";
import { useSaved } from "@/lib/saved";
import type { BandRule } from "@/lib/state";
import type { IndexPlace } from "@/lib/types";
import { DownloadIcon, InstallSheet } from "./InstallSheet";
import { Search } from "./Search";
import { Tiles } from "./Tiles";
import { largestPlaces } from "./logic";
import s from "./home.module.css";

const OfflineIcon = (
  <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flex: "none" }}>
    <path d="M2 9a15 15 0 0 1 6-3.4" />
    <path d="M12 5a15 15 0 0 1 10 4" />
    <path d="M5.5 12.5a10 10 0 0 1 4-2.3" />
    <path d="M15 10.6a10 10 0 0 1 3.5 1.9" />
    <path d="M9 16a5 5 0 0 1 6 0" />
    <path d="M12 19.5h.01" />
    <path d="M3 3l18 18" />
  </svg>
);

const AUTO_OFFER = false;

export function HomeScreen({ places, bands }: { places: IndexPlace[]; bands: BandRule[] }) {
  const { t } = useI18n();
  const online = useOnline();
  const saved = useSaved();
  const install = useInstall();
  const [sheet, setSheet] = useState(false);
  const offered = useRef(false);

  const fallback = saved !== null && saved.length === 0;
  const big = useMemo(() => largestPlaces(places), [places]);
  const stations = saved === null ? null : fallback ? big : saved;

  // The sheet opens from the button only. Offering it unasked to a returning visitor is an
  // owner decision (not on the canvas): set AUTO_OFFER to true to turn it on.
  const { mode, laterAt } = install;
  useEffect(() => {
    if (!AUTO_OFFER || offered.current || mode == null || saved == null || !online) return;
    if (shouldAutoOffer(mode, saved.length > 0, laterAt, Date.now())) {
      offered.current = true;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time offer once the device is read
      setSheet(true);
    }
  }, [mode, laterAt, saved, online]);

  const closeSheet = () => {
    install.later();
    setSheet(false);
  };

  return (
    <Screen ground="papier" className={`${s.root}${online ? "" : ` ${s.offline}`}`}>
      <div className={s.page}>
        <Header>
          <MethodLink />
        </Header>

        {online ? null : (
          <div role="status" className={s.banner}>
            {OfflineIcon}
            <p>
              <strong>{t.home.offlineBold}</strong> {t.home.offlineBody}
            </p>
          </div>
        )}

        <div className={s.hero}>
          <h1 className={s.title}>
            <label htmlFor="recherche">{t.home.searchLabel}</label>
          </h1>
          <Search places={places} offline={!online} />
        </div>

        {stations ? (
          <section className={s.saved} aria-labelledby="home-saved">
            <h2 id="home-saved" className={s.sectionTitle}>
              {fallback ? t.home.bigHeading : t.home.savedHeading}
            </h2>
            <Tiles stations={stations} bands={bands} online={online} />
          </section>
        ) : null}

        {mode && mode !== "none" ? (
          <div className={s.installRow}>
            <button type="button" className={s.installBtn} onClick={() => setSheet(true)} aria-haspopup="dialog">
              <span aria-hidden="true" className={s.installIcon}>
                {DownloadIcon}
              </span>
              {t.home.installButton}
            </button>
          </div>
        ) : null}
      </div>

      {sheet && mode && mode !== "none" ? (
        <InstallSheet
          mode={mode}
          onInstall={() => {
            void install.install().then((accepted) => {
              if (accepted) setSheet(false);
              else closeSheet();
            });
          }}
          onClose={closeSheet}
        />
      ) : null}
    </Screen>
  );
}
