"use client";

import { useI18n } from "./I18n";
import { formatDate } from "@/lib/i18n";
import type { Attribution, Period } from "@/lib/types";

export function About({ period, attribution }: { period: Period; attribution: Attribution }) {
  const { lang } = useI18n();
  const s = formatDate(period.start, lang);
  const e = formatDate(period.end, lang);
  const src = (
    <a href={attribution.source_url} rel="noopener">
      {attribution.source}
    </a>
  );
  const lic = (
    <a href={attribution.license_url} rel="noopener">
      ODbL
    </a>
  );
  if (lang === "en")
    return (
      <article className="prose">
        <h1>Method &amp; data</h1>
        <h2>What the score means</h2>
        <p>
          For each metro and RER station, the <strong>crowding score</strong> compares the number of
          people entering the station in a given hour with that station&apos;s own{" "}
          <strong>reference level</strong>: the level of its busiest hours over the last 12 months
          (95th percentile of hourly entries). 100 means a typical rush hour for that station; above
          100 is exceptional. Scores compare hours at one station, not stations with each other.
        </p>
        <ul>
          <li>Quiet: below 40 · Moderate: 40–69 · Busy: 70–99 · Very busy: 100 and above.</li>
          <li>
            The <strong>typical week</strong> averages days of the same type: weekdays and Saturdays
            in term time or school holidays, and Sundays with public holidays.
          </li>
          <li>Expected entries are shown alongside, rounded: they are raw validation counts.</li>
        </ul>
        <h2>How it is computed</h2>
        <ol>
          <li>Daily entries per station from {src} open data, {s} to {e}.</li>
          <li>
            Days with data problems, strikes or network-wide disruptions are left out. Each day type
            gets its average daily level.
          </li>
          <li>
            The hourly profile of each day type is the average of the last four quarterly profiles
            published by IDFM.
          </li>
          <li>Expected entries per hour = daily level × hourly share; score = 100 × expected / reference.</li>
        </ol>
        <h2>Limitations</h2>
        <ul>
          <li>
            Only <strong>entries from the street</strong> are counted: no exits, no transfers inside a
            station. The score is not how full the trains are.
          </li>
          <li>
            People who do not validate (paper tickets in older years, fare evasion, open gates) are
            missing, so counts are lower than real traffic. The score is relative, so this matters less.
          </li>
          <li>
            Some stations share one counting point in the data (e.g. Châtelet and the RER at
            Châtelet – Les Halles).
          </li>
          <li>This is a typical week, not a forecast for a specific date. Events, works and strikes are not included.</li>
        </ul>
        <h2>Data and licences</h2>
        <p>
          Source: {src}, validation data on the rail network and stop and line references ({lic}).
          The derived data published here (files under <code>/data/</code>) is under {lic}. The code is
          open source under the MIT licence. This is an independent project, not affiliated with
          IDFM, RATP or SNCF.
        </p>
      </article>
    );
  return (
    <article className="prose">
      <h1>Méthode et données</h1>
      <h2>Ce que signifie le score</h2>
      <p>
        Pour chaque station de métro et de RER, le <strong>score d’affluence</strong> compare le nombre
        de personnes qui entrent dans la station pendant une heure au <strong>niveau de référence</strong>{" "}
        de cette même station : le niveau de ses heures les plus chargées sur les 12 derniers mois
        (95ᵉ centile des entrées horaires). 100 correspond à une heure de pointe habituelle pour la
        station ; au-delà, c’est exceptionnel. Le score compare les heures d’une même station, pas les
        stations entre elles.
      </p>
      <ul>
        <li>Calme : moins de 40 · Modéré : 40 à 69 · Chargé : 70 à 99 · Très chargé : 100 et plus.</li>
        <li>
          La <strong>semaine type</strong> fait la moyenne des jours du même type : semaine et samedi, en
          période scolaire ou pendant les vacances, et dimanches avec jours fériés.
        </li>
        <li>Le nombre d’entrées attendu est affiché à côté, arrondi : ce sont des validations brutes.</li>
      </ul>
      <h2>Comment il est calculé</h2>
      <ol>
        <li>Entrées quotidiennes par station, données ouvertes d’{src}, du {s} au {e}.</li>
        <li>
          Les jours avec un problème de données, de grève ou de perturbation générale sont écartés.
          Chaque type de jour reçoit son niveau quotidien moyen.
        </li>
        <li>
          Le profil horaire de chaque type de jour est la moyenne des quatre derniers profils
          trimestriels publiés par IDFM.
        </li>
        <li>Entrées attendues par heure = niveau quotidien × part horaire ; score = 100 × attendu / référence.</li>
      </ol>
      <h2>Limites</h2>
      <ul>
        <li>
          Seules les <strong>entrées depuis la rue</strong> sont comptées : ni les sorties, ni les
          correspondances dans la station. Le score ne dit pas si les trains sont pleins.
        </li>
        <li>
          Les voyageurs qui ne valident pas (tickets magnétiques les années passées, fraude, portiques
          ouverts) manquent : les comptages sont inférieurs au trafic réel. Le score étant relatif, cela
          pèse moins.
        </li>
        <li>
          Certaines stations partagent un même point de comptage dans les données (par exemple Châtelet
          et le RER à Châtelet – Les Halles).
        </li>
        <li>
          Il s’agit d’une semaine type, pas d’une prévision pour une date précise : événements, travaux
          et grèves ne sont pas pris en compte.
        </li>
      </ul>
      <h2>Données et licences</h2>
      <p>
        Source : {src}, données de validation sur le réseau ferré et référentiels des arrêts et des
        lignes ({lic}). Les données dérivées publiées ici (fichiers sous <code>/data/</code>) sont sous{" "}
        {lic}. Le code est libre, sous licence MIT. Projet indépendant, sans lien avec IDFM, la RATP ou
        la SNCF.
      </p>
    </article>
  );
}
