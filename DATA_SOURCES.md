# Data sources

Verify every URL and dataset ID via the data.gouv.fr API or the portal before downloading. Fill in URL, license, attribution and date checked for each source as it is verified.

| # | Dataset | Where | Use | URL | License | Attribution | Checked |
|---|---|---|---|---|---|---|---|
| 1 | Validations réseau ferré — nombre de validations par jour (NB_FER), all semesters/quarters since 2015 | data.iledefrance-mobilites.fr / data.gouv.fr | Daily entries per station × ticket type | | | | |
| 2 | Validations réseau ferré — profils horaires par jour type (PROFIL_FER) | same | Hourly share of entries per day type | | | | |
| 3 | Validation data documentation (PDF) | attached to the datasets | Codes, day types, caveats | | | | |
| 4 | IDFM stop reference (référentiel des arrêts / zones d'arrêt, ID_REFA_LDA) | data.iledefrance-mobilites.fr | Join validations ↔ GTFS ↔ coordinates | | | | |
| 5 | IDFM GTFS (timetables) | PRIM / transport.data.gouv.fr | Scheduled departures per stop × hour | | | | |
| 6 | Offre par tranche horaire (IDFM) | data.iledefrance-mobilites.fr | Cross-check of service per time slot | | | | |
| 7 | Weather — Open-Meteo Historical API (hourly, ERA5) and/or Météo-France (station Paris-Montsouris) | open-meteo.com / meteo.data.gouv.fr | Rain, temperature | | | | |
| 8 | Public holidays | calendrier.api.gouv.fr | Calendar features | | | | |
| 9 | School holidays (zone C) | data.education.gouv.fr (calendrier scolaire) | Calendar features | | | | |
| 10 | Rolling-stock capacity per line | manual table (sources cited) | Occupancy ratio | | | | |
| 11 | Fare-evasion rates by mode (IDFM, RATP, SNCF publications: reports, press releases, open data if any) | operator sites | Correct validation undercounting | | | | |
| 12 | PRIM "Messages Info Trafic" API (unplanned + planned disruptions, incl. scheduled works; RATP, SNCF, other operators) | prim.iledefrance-mobilites.fr (free API key) | Live disruptions, planned closures | | | | |
| 13 | PRIM worksite and traffic-info datasets (monthly works) | prim.iledefrance-mobilites.fr | Planned works, backfill | | | | |
| 14 | PRIM itinerary calculator — disruptions endpoint | prim.iledefrance-mobilites.fr | Fallback if #12 is incomplete | | | | |
| 15 | Real-time departures (PRIM "Prochains passages" / SIRI, GTFS-RT if available) | prim.iledefrance-mobilites.fr | Actual vs scheduled service | | | | |
| 16 | News archives (e.g. GDELT, press search) and official strike announcements | web | Fallback labels for past strikes and incidents | | | | |

## License constraints inherited from the sources
- **IDFM validations and GTFS:** mostly ODbL. Verify each dataset on the IDFM portal, since some mirrors show "license not specified."
  - Attribution is required.
  - Any published derived database (cleaned tables, forecasts) must also be ODbL (share-alike).
  - Code is not affected.
- **Météo-France and calendar APIs:** Licence Ouverte / Etalab 2.0; attribution required.
- **Open-Meteo:** data under CC BY 4.0; the free API is for non-commercial use. Re-check its terms before any commercial use.

Code and data are licensed separately. Code license: MIT (see `LICENSE`).

Licensing notes are not legal advice.
