# Data sources

Verify every URL and dataset ID via the data.gouv.fr API or the portal before downloading. Fill in URL, license, attribution and date checked for each source as it is verified.

| # | Dataset | Where | Use | URL | License | Attribution | Checked |
|---|---|---|---|---|---|---|---|
| 1 | Validations réseau ferré — nombre de validations par jour (NB_FER), all semesters/quarters since 2015 | data.iledefrance-mobilites.fr / data.gouv.fr | Daily entries per station × ticket type | 2015–2025: `https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/histo-validations-reseau-ferre` (yearly zips); current: `validations-reseau-ferre-nombre-validations-par-jour-{1er,2eme,3eme,4eme}-trimestre` (rolling, overwritten each year) | ODbL (Q2 2026 datasets show Licence Ouverte v2.0; recorded per file in the manifest) | Île-de-France Mobilités | 2026-11-11 |
| 2 | Validations réseau ferré — profils horaires par jour type (PROFIL_FER) | same | Hourly share of entries per day type | yearly zips (same as #1); current: `validations-reseau-ferre-profils-horaires-par-jour-type-{1er,2eme,3eme,4eme}-trimestre` | ODbL (per file in manifest) | Île-de-France Mobilités | 2026-11-11 |
| 3 | Validation data documentation (PDF) | attached to the datasets | Codes, day types, caveats | `https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/histo-validations-reseau-ferre/attachments/donnees_de_validation_pdf` | ODbL | Île-de-France Mobilités | 2026-11-11 |
| 4 | IDFM stop reference (référentiel des arrêts / zones d'arrêt, ID_REFA_LDA) | data.iledefrance-mobilites.fr | Join validations ↔ GTFS ↔ coordinates | `zones-de-correspondance` (validation `ida` = ZdC id), `zones-d-arrets`, `arrets`; CSV export, dated snapshot | Licence Ouverte v2.0 | Île-de-France Mobilités | 2026-11-11 |
| 5 | IDFM GTFS (timetables) | PRIM / transport.data.gouv.fr | Scheduled departures per stop × hour | | | | |
| 6 | Offre par tranche horaire (IDFM) | data.iledefrance-mobilites.fr | Cross-check of service per time slot | | | | |
| 7 | Weather — Open-Meteo Historical API (daily) | open-meteo.com | Rain, snow, temperature (Paris) | `GET https://archive-api.open-meteo.com/v1/archive` with `latitude=48.8566&longitude=2.3522&daily=precipitation_sum,snowfall_sum,precipitation_hours,temperature_2m_max,temperature_2m_min&timezone=Europe/Paris`; `end_date` ≤ today (last days are forecasts) | CC BY 4.0; free API non-commercial | "Weather data by Open-Meteo.com" | 2026-11-11 |
| 8 | Public holidays (metropole) | calendrier.api.gouv.fr | Calendar features | `https://calendrier.api.gouv.fr/jours-feries/metropole.json` (`{date: name}`, 2006–2031 on 2026-11-11) | Not stated on the data.gouv.fr dataservice page (producer DINUM) | DINUM / data.gouv.fr | 2026-11-11 |
| 9 | School holidays (zone C) | data.education.gouv.fr | Calendar features | `https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-calendrier-scolaire/exports/csv?delimiter=%3B` (fields description, population, start_date, end_date, location, zones, annee_scolaire); Zone C / Paris from 2017-2018 only | Licence Ouverte v2.0 (Etalab) | Ministère de l'Éducation nationale | 2026-11-11 |
| 10 | Rolling-stock capacity per line | manual table (sources cited) | Occupancy ratio | | | | |
| 11 | Fare-evasion rates by mode (IDFM, RATP, SNCF publications: reports, press releases, open data if any) | operator sites | Correct validation undercounting | | | | |
| 12 | PRIM "Messages Info Trafic" API (unplanned + planned disruptions, incl. scheduled works; RATP, SNCF, other operators) | prim.iledefrance-mobilites.fr (free API key) | Live disruptions, planned closures | `GET https://prim.iledefrance-mobilites.fr/marketplace/disruptions_bulk/disruptions/v2`, header `apikey`; JSON `disruptions`, `lines`, `lastUpdatedDate`; quota 1000 req/day for new tokens | | | 2026-10-25 (endpoint) |
| 13 | PRIM worksite and traffic-info datasets (monthly works) | prim.iledefrance-mobilites.fr | Planned works, backfill | | | | |
| 14 | PRIM itinerary calculator — disruptions endpoint | prim.iledefrance-mobilites.fr | Fallback if #12 is incomplete | | | | |
| 15 | Real-time departures (PRIM "Prochains passages" / SIRI, GTFS-RT if available) | prim.iledefrance-mobilites.fr | Actual vs scheduled service | | | | |
| 16 | News archives (e.g. GDELT, press search) and official strike announcements | web | Fallback labels for past strikes and incidents | | | | |
| 17 | IDFM "Arrêts et lignes associées" (`arrets-lignes`) | data.iledefrance-mobilites.fr | Stop → line → mode; v0 scope (metro, RER, T4) and line badges | `https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/arrets-lignes/exports/csv?delimiter=%3B`; `stop_id` = `IDFM:monomodalStopPlace:<zdaid>` (rail) or `IDFM:<arrid>` (metro, tram); `mode` = Metro, RapidTransit (RER), LocalTrain, regionalRail, Tramway… | ODbL | Île-de-France Mobilités | 2026-11-12 |
| 18 | IDFM "Référentiel des lignes" (`referentiel-des-lignes`) | data.iledefrance-mobilites.fr | Line codes, short names, network (RER, Transilien), web colours | `https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/referentiel-des-lignes/exports/csv?delimiter=%3B`; joined on `id_line` = arrets-lignes `id` without `IDFM:` | ODbL | Île-de-France Mobilités | 2026-11-12 |

## License constraints inherited from the sources
- **IDFM validations and GTFS:** mostly ODbL. Verify each dataset on the IDFM portal, since some mirrors show "license not specified."
  - Attribution is required.
  - Any published derived database (cleaned tables, forecasts) must also be ODbL (share-alike).
  - Code is not affected.
- **Météo-France and calendar APIs:** Licence Ouverte / Etalab 2.0; attribution required.
- **Open-Meteo:** data under CC BY 4.0; the free API is for non-commercial use. Re-check its terms before any commercial use.

Code and data are licensed separately. Code license: MIT (see `LICENSE`).

Licensing notes are not legal advice.
