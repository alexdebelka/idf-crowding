"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/components/I18n";
import { Header, MethodLink, Screen } from "@/components/shared/Header";
import { shouldAutoOffer, useInstall } from "@/lib/install";
import { useOnline } from "@/lib/online";
import { useFavourites } from "@/lib/favourites";
import { useSaved } from "@/lib/saved";
import type { BandRule } from "@/lib/state";
import type { IndexPlace } from "@/lib/types";
import { DownloadIcon, InstallSheet } from "./InstallSheet";
import { Search } from "./Search";
import { Tiles } from "./Tiles";
import { homeSections, largestPlaces } from "./logic";
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
  const favourites = useFavourites();
  const install = useInstall();
  const [sheet, setSheet] = useState(false);
  const offered = useRef(false);

  const big = useMemo(() => largestPlaces(places), [places]);
  const sections = saved === null || favourites === null ? null : homeSections(favourites, saved, big);
  const heading = { favourites: t.home.savedHeading, recent: t.home.recentHeading, big: t.home.bigHeading };

  // The sheet opens from the button only. Offering it unasked to a returning visitor is an
  // owner decision (not on the canvas): set AUTO_OFFER to true to turn it on.
  const { mode, laterAt } = install;
  useEffect(() => {
    if (!AUTO_OFFER || offered.current || mode == null || saved == null || !online) return;
    if (shouldAutoOffer(mode, saved.length > 0 || (favourites?.length ?? 0) > 0, laterAt, Date.now())) {
      offered.current = true;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time offer once the device is read
      setSheet(true);
    }
  }, [mode, laterAt, saved, favourites, online]);

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

        {sections?.map((sec, i) => (
          <section key={sec.kind} className={s.saved} aria-labelledby={`home-${sec.kind}`}>
            <h2 id={`home-${sec.kind}`} className={s.sectionTitle}>
              {heading[sec.kind]}
            </h2>
            {i === 0 && sec.kind !== "favourites" ? <p className={s.favHint}>{t.home.favHint}</p> : null}
            <Tiles stations={sec.stations} bands={bands} online={online} />
          </section>
        ))}

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
