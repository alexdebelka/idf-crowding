# Data-quality decisions

Decisions needed to reproduce the harmonized validation tables (`idf-clean all`).
Code: `src/idf_crowding/clean/`. Each rule has a test in `tests/test_clean_*.py`.
A regenerated numeric report is written to `data/processed/quality/report.md`.

Source: IDFM rail validations (NB_FER daily counts, PROFIL_FER hourly profiles), 2015 S1 to
the latest published quarter, plus the IDFM documentation PDF (`Donnees_de_validation.pdf`).

## What the data counts (from the IDFM documentation)
- Entries from the street into the rail network only. Exits and transfers are excluded.
- Not counted: magnetic tickets, people who do not validate, fare evaders, gates that are
  out of service (e.g. during works). Validations are therefore a lower bound of traffic.
- One row per operator stop code (transporter, network, stop) × date × ticket category.
- `JOUR` is the operating day, 04:00 to 03:59 the next day.
- Hourly profiles are averages over the whole publication period (half-year, then quarter)
  for five day types: JOHV (working day, no school holidays), SAHV (Saturday, no school
  holidays), JOVS (working day, school holidays), SAVS (Saturday, school holidays),
  DIJFP (Sundays, public holidays and bridge days).
- Tram T4 is counted as rail (per stop); other trams only per line (not used).

## Reading the raw files
| Issue | Files | Rule |
|---|---|---|
| Format | 2015: `.csv`; 2016 to 2024: `.txt`; 2025: `.xlsx`; API exports: `.csv` | Read all as text columns; xlsx via `fastexcel` |
| Separator | `;` (2015, 2022 S2, exports) or tab (others) | Tab if the header line has a tab, else `;` |
| Encoding | UTF-16 (2023 S2 NB), UTF-8 with BOM (2022 S2), cp1252 (2023 S1, 2023 S2 PROFIL, 2024 S1), UTF-8 | BOM detection, then UTF-8, fallback cp1252 |
| Column names | Station id is `ID_REFA_LDA`, `lda`, `ID_ZDC`, `ida` or `id_zdc`; date is `JOUR` or `DATE` (2025 T2); share is `POURC_VALIDATIONS` or `POURCENTAGE_VALIDATIONS`; case varies | Alias table to one canonical schema; an unknown column is an error |
| Dates | `dd/mm/yyyy`; `dd/mm/yy` (2024 T3); ISO (2024 T4, xlsx, exports) | Parse by pattern, never guess |
| Numbers | Left-padded with spaces (2016 to 2022); thousands separator space (2024 T3: `1 020`); floats (`71379.0`, `251.0`) | Strip all whitespace, parse as float, round to integer |
| Periods | Half-years `S1/S2` to 2024 S1, then quarters `T1`–`T4` (stored as `Q1`–`Q4`) | Period parsed from the file name |
| Nested copies | The 2020 zip contains the 2015–2019 zips again | Nested zips are skipped |
| Overlaps | 2025 Q3 and Q4 exist in the yearly archive and in the rolling quarterly datasets (identical totals) | Per date, keep one source: yearly archive first, then rolling quarterly |

## Small counts (masking)
Three regimes, detected per file from the data (not from the year):

| Regime | Files | Meaning | Rule |
|---|---|---|---|
| `lt5_text` | 2015 S1 – 2017 S1 | "Moins de 5" = 1 to 4 | `n_validations` null, `is_masked` true |
| `le5_as5` | 2017 S2 – 2023 S1 | No value below 5; "5" = 1 to 5 (the documentation's variable table) | value kept as 5, `is_masked` true |
| `none` | 2023 S2 onwards | Exact values from 1 | no masking |

Daily station totals count each masked row as **3** entries (`MASKED_IMPUTE`) and keep
`n_exact` and `n_masked_rows` next to the total. Imputed entries are < 0.11 % of the total
in every year.

## Station identity
- **Station id = ZdC id** (zone de correspondance) from the IDFM stop reference. A ZdC can
  hold several operator stop codes (e.g. RATP metro, RATP RER and SNCF at one hub); their
  entries are summed, never split by line.
- ZdC ids `0`, `-1` and `999999` are placeholders (rows labelled "Inconnu", or no id yet)
  and are treated as missing.
- The id is missing in some files (2015 S1 – 2017 S1, 2024 T4, 2025 T2–T3, 2026) and 57 stop
  codes changed ZdC over time. Each stop code is mapped to the ZdC of its most recent row,
  preferring ids present in the current stop reference. Rows with neither a stop code nor a
  ZdC ("Inconnu") are dropped: about 0.05 % of validations.

## Ticket categories
Two vocabularies (to 2023 S1 and from 2023 S2) mapped to approximate groups: `navigo`,
`imagine_r`, `amethyste`, `solidarity` (TST, FGT, Contrat Solidarité Transport),
`short_passes` (Navigo Jour, Forfaits courts), `other`, `undefined` ("?", NON DEFINI).
The v0 model uses totals over all categories, so the grouping is not load-bearing.

Known break: `short_passes` jumps from 17 M (2024) to 338 M (2025) validations as
magnetic tickets were replaced by contactless media that are counted. Network totals are
not comparable across this break without a correction.

## Hourly profiles
- Share is converted from percent to a fraction. Slot `ND` (not determined, < 0.1 %) is
  dropped and the remaining shares rescaled to sum to 1.
- A station with several stop codes gets their profiles averaged, weighted by each stop
  code's validations over the same period.

## Quality flags (never delete data)
- `missing`: no row for a station on a date inside its active span.
- `low` / `high`: station total below 30 % or above 300 % of the centred 9-week rolling
  median of the same weekday, on a day when the network total is within 70–150 % of its
  own usual level (so strikes and holidays are not blamed on one station).
- Level shifts: station-months whose mid-week level relative to the network moves by more
  than ×1.5 vs the mean of the previous 3 months (March 2020 – December 2021 skipped).
  Catches station closures for works, new lines and id changes.

These flags are used later to exclude days from training and from the Reference level.

## Features (`idf-features build` → `data/processed/features_daily.parquet`)
One row per station × date, target `n_entries`. Station-days flagged `missing` are added
as explicit rows with a null target. A source that is not downloaded gives null columns
(with a warning), never guessed values.

| Feature | Rule |
|---|---|
| `is_public_holiday` | Listed by calendrier.api.gouv.fr (metropole) |
| `is_school_holiday` | Zone C, location Paris, population "-" or "Élèves" (teachers' rows ignored). `start_date`/`end_date` are UTC instants of local midnights: holiday = local dates start ≤ d < end. Null outside coverage (from 1 Sept of the first school year, i.e. 2017-09-01, to the last listed holiday end) |
| `is_bridge` | Monday before a Tuesday holiday, Friday after a Thursday holiday (not itself a holiday) |
| `day_type` | DIJFP if Sunday, holiday or bridge; else SAVS/SAHV (Saturday in/out of school holidays); else JOVS/JOHV. Null if any input is null (so before 2017-09 until another school-calendar source is added) |
| `is_covid` | 2020-03-17 to 2021-06-30 |
| `is_strike_2019` | 2019-12-05 to 2020-01-19 (pension-reform strike) |
| weather | Open-Meteo daily for Paris (one grid cell), latest download; `precip_mm`, `snow_cm`, `precip_hours`, `tmax_c`, `tmin_c` |
| `short_pass_share` | Share of `short_passes` in all network validations of the date's month (2025 ticket change); after the last published month: last value; before the first: first value |
| `station_type` | k-means (k = 3) on JOHV hourly shares of the last 4 published quarters; clusters named by share of entries 7–10 h: highest `origin`, lowest `destination`, middle `mixed`. Stations without a profile in all 4 quarters (new stations, stations missing from some files) are assigned to the nearest cluster centre from their own profile: mean of the quarters they have, else their most recent published period; they do not move the centres. Null only without any profile |
| `quality_flag`, `network_ratio` | From `quality/`: missing / low / high; network total ÷ its rolling weekday median |

Caveat for backtests: `short_pass_share` and `station_type` are computed from data that
includes the test period. Freeze both at the forecast origin when evaluating.

## Backtest (`idf-backtest`, `make backtest` → `data/processed/backtest/`)
Rolling origin, time splits only. Rules in `src/idf_crowding/models/`.

| Rule | Value |
|---|---|
| Origins | First day of the month; the last origin is the latest whose full horizon fits in the data; 12 origins, one month apart |
| Horizon | 1–60 days (horizon 1 = the origin date); buckets 1–7, 8–28, 29–60 |
| Training rows | From 2022-01-01 to the day before the origin, clean rows only |
| Left out of training and scoring | Target missing (`missing`); COVID; 2019 strike; **network disruption day** = day type JOHV or SAHV with `network_ratio` < 0.8 (strikes, snow; holiday dips are JOVS/SAVS/DIJFP and stay in); **closure** (below); station flags `low` / `high`. Counts per reason in `exclusions.parquet` and the report |
| Closure | Station share of network entries that day < 0.4 × its median share on the same day group (working day / Saturday / Sunday-holiday) over the previous 365 days (≥ 20 such days). Past days only, so it is valid for training rows; catches long closures that the centred-median `low` flag misses. Forecasts assume normal service: planned works are to be shown as warnings |
| Scored rows | Clean rows where every model has a prediction (a baseline needs history at that station: otherwise `no_baseline`) |
| `short_pass_share` at origin | Dates ≥ origin get the value of the last month before the origin |
| `station_type`, `am_share_7_10` at origin | k-means on the most recent profile periods that ended before the origin, until they cover ≥ 12 months (4 quarters; quarters + a semester, or 2 semesters, before mid-2024). Stations missing from some of those periods: nearest centre, using only periods that ended before the origin |
| Weather | Observed (not forecast). Fitting without weather changed WAPE by 0.001, so the variant is off by default (`weather_variant`) |
| `naive_4w` | Same weekday, mean of the clean days of the last 4 weeks before the origin |
| `daytype_12m` | Per station and day type, mean of the clean days of the last 365 days |
| `lgbm` | One global LightGBM, Tweedie objective, 600 rounds; station id as a dense categorical code; no lags; `t_days` (days since training start) and recency weights 0.5^(age / 365 days) |
| Metrics | WAPE (main) = Σ\|y − ŷ\| / Σy; MAE; MAPE on station-days with y ≥ 100 (smaller counts make it explode); network level = errors of the daily total of scored stations |
| Intervals (80 %) | Calibrated on a forecast log: the out-of-sample forecasts of earlier origins (12 extra warm-up origins before the first scored one, not reported) for clean days of the 365 days before the origin. `conformal` = point + empirical quantiles of log1p residuals; `cqr` = LightGBM quantiles (10 %, 90 %, on log1p, 300 rounds) widened by the conformal quantile of max(q10 − y, y − q90) in log space; `quantile` = raw LightGBM quantiles. Groups: day type × station type × horizon bucket, falling back to day type × horizon bucket, then horizon bucket, below 500 rows. Finite-sample conformal levels. Scores: coverage, relative width, Winkler interval score / Σy |
| Deep models (option C) | `idf-deep export`: per origin, complete daily grid from each station's first clean day; excluded or absent days get `available_mask` = 0 and an interpolated log1p target (inputs only, never scored); future exogenous = calendar, day type, frozen `short_pass_share`, weather z-scored with pre-origin statistics; static = frozen station type and morning share, log mean entries of the last 365 days. Stations with < 365 clean days or none in the last 28 days are left out (LightGBM only). `idf-deep score` uses exactly the LightGBM scored rows. Lag variants (`--lag N --weather production`): history ends at the cutoff c, future rows c .. origin + 59 (model h = N + 60) with observed calendar and weather on the gap, climatology after day 16; static features and weather z-scores from data before c; the gap rows are never scored. With several seeds that all have the warm-up origins, the ensemble band is calibrated on the seed average |
| Publication lag (variants) | `--lag N` (`lag_days`): data cutoff c = origin − N days. Everything that the main backtest takes "before the origin" is taken before c instead: training rows, frozen `short_pass_share` and station type / morning share (profile periods ended before c), `naive_4w` (4 weeks before c), `daytype_12m` (365 days before c), busy thresholds, interval calibration rows (earlier origins' forecasts dated in [c − 365, c)). The gap c .. origin − 1 is not forecast; scored dates and exclusion rules are those of the main backtest. `days_since_data` = N + horizon. Results in `backtest/variants/lagN_obs\|prod/`; `idf-backtest summary` compares variants. Lags tried: 75 / 120 / 165 days (IDFM publishes a quarter ~70–76 days after it ends, so the last data day is 75–165 days old at issue time) |
| Production weather (variants) | `--weather production`: observed weather for days 1–16 after the origin (stands in for a weather forecast; forecast error ignored), then day-of-year climatology = mean of all dates before c within ± 7 calendar days (weather since 2015). Training rows keep observed weather |
| Busy day | Entries above the station's 90th percentile of clean days of the same day group over the 365 days before the origin (before c with a lag). P(busy) from the conformal residual distribution (grid 5–95 %, linear CDF, tails clamped at 2.5 / 97.5 %). Scores: Brier, reliability bins. A seasonal threshold and a logistic recalibration were tried on the production-like log and not accepted: see "P(busy day) recalibration" below |

Known limits: profiles and validations are published months after the fact, so a real
forecast made today has a longer effective horizon than the main backtest (see the lag
variants); planned works and station closures are not in the features yet.

## Production forecast (`idf-forecast`, `make forecast-lgbm|forecast-export|forecast-combine` → `data/processed/forecast/CUTOFF/`)
Decision record: `docs/adr/0002-production-forecast-per-release.md`.

| Rule | Value |
|---|---|
| Cutoff | Day after the last date with published validations (`n_entries` not null) |
| Issue date | First forecast date; default today. Refused if after cutoff + `days_max` − 1 |
| Horizon | Forecast to cutoff + `days_max` − 1 (225 days: ~75 days of publication delay + ~90 to the next release + 60). Reported per row: `horizon` (days since the issue date) and `days_since_data` |
| Stations | A clean day (target present, no quality flag) in the 28 days before the cutoff |
| Future calendar | From the ingested public-holiday and school-holiday sources (`features/calendar.py`); null where a source does not cover the date |
| Future weather | Observed where already downloaded, then day-of-year climatology (± 7 days, all observed years); `weather_source` per row |
| Frozen at the cutoff | `short_pass_share` (last value), station type and morning share (profile periods ended before the cutoff) |
| LightGBM | Same configuration as the backtest, fitted on all clean rows from `train_start` to the day before the cutoff |
| TFT | `idf-deep export --production`: one origin = the cutoff, h = `days_max`; 3 seeds on a GPU; mean of the seeds' medians |
| Point | mean(LightGBM, TFT seed mean); LightGBM alone for stations without TFT (fewer than 365 clean days) or without `--deep` (`model` column) |
| 80 % band | Conformal: residual quantiles of the production-like backtest (variant `lag120_prod`: ensemble log for the ensemble, LightGBM log for LightGBM alone) dated in the 365 days before the cutoff, by day type × station type × horizon bucket (horizon = days since the issue date, buckets capped at 29–60) |
| Not produced | P(busy day): not calibrated well enough at the publication lag (see "P(busy day) recalibration") |
| Growth | LightGBM × year-on-year growth of its weekday class projected from the cutoff (columns `lgbm`, `lgbm_raw`, `growth`); see "Growth extrapolation" below |
| Special days | Dec 24, Dec 25, Dec 31, Jan 1: LightGBM × a per-station factor (point and band), not the ensemble; columns `special_day`, `adjust` (1 on other dates); raw `lgbm` / `tft` kept. See "Special days" below |

### Special days (`models/special_days.py`)
**Finding.** In the production-like backtest (variant `lag120_prod`, forecasts 4–6 months ahead), both Christmas seasons were over-forecast at network level while a typical day is within ~±6 % (median absolute network error of the ensemble). Network error, forecast / actual − 1 (ensemble / LightGBM / TFT), mean of the origins covering the date:

| date | 2024/25 | 2025/26 |
|---|---|---|
| Dec 24 | +36 % / +8 % / +65 % | +23 % / +11 % / +35 % |
| Dec 25 | +44 % / +27 % / +62 % | +32 % / +28 % / +35 % |
| Dec 31 | +67 % / +21 % / +113 % | +42 % / +14 % / +70 % |
| Jan 1 | +49 % / +2 % / +96 % | +38 % / +7 % / +67 % |

These 4 dates exceed |log ratio| 0.15 in both years; Dec 26 and Jan 2 do not (Dec 26 2025 and Jan 2 2026 are typed DIJFP by the calendar source). They are not excluded from training: the disruption rule only applies to JOHV/SAHV. Their day types (JOVS, DIJFP) group them with ordinary holiday days; TFT only has a smooth day of year, LightGBM few years. Other dates with large errors go the other way (under-forecast) and are only seen once (Jul 14, May 2025 bridge days, Whit Monday ≈ −20 %; summer 2024 = Olympics); many Sundays are under-forecast by 15–20 %. Not corrected.

**Factor.** Per station × special day, from the LightGBM forecast log (warm-up + scored origins) with outcomes dated before the cutoff, clean rows only (`exclude` null):
- r = log1p(y) − log1p(lgbm), averaged over the origins covering a date, then the median over years (seasons: Jan 1 belongs to the previous December).
- A station-year counts only if the station had ≥ 730 days of data at that forecast's cutoff: young stations' errors shrink as their history grows (Orly, opened 2024-07: LightGBM Jan 1 forecasts 0.6–0.8 k in 2024/25 and 2.6–3.0 k in 2025/26 vs 10–12 k actual; an unfiltered factor would have been ×4.1).
- Shrunk to the station-type target (median of the station-year ratios of that type; network median for untyped stations): log f = w · log f_station + (1 − w) · log f_type, w = n / (n + k), k = 2, n = years. Stations without own history get the type target.
- Applied as point × f, lo × f, hi × f (the band is multiplicative in log space).

**Validation (leave one year out).** Factors from Christmas 2024 (cutoff 2025-07-01), applied to the Christmas 2025 forecasts of the backtest (4 951 station-days, 4 dates):

| variant | station WAPE | 80 % band coverage | network error Dec 24 / 25 / 31 / Jan 1 |
|---|---|---|---|
| ensemble (before) | 0.337 | 0.38 | +23 / +32 / +42 / +38 % |
| ensemble × factor (k = 2) | 0.163 | 0.73 | −13 / −13 / −17 / −12 % |
| LightGBM | 0.210 | 0.59 | +11 / +28 / +14 / +7 % |
| **LightGBM × factor (k = 2)** | **0.130** | **0.79** | **+3 / −3 / −5 / +4 %** |

k = 1 / 4 give 0.132 / 0.133. The ensemble factor overshoots because TFT's Christmas error roughly halved from 2024 to 2025 (not stable); LightGBM's was stable. Only one validation year: re-check after Christmas 2026.

**First production run** (cutoff 2026-07-01, before the growth correction): network totals Dec 24 / 25 / 31 / Jan 1 = 4.50 / 2.28 / 3.14 / 2.30 M (before: 5.89 / 3.48 / 5.21 / 3.27), i.e. −1 / −6 / −8 / +17 % vs the same date a year earlier (ordinary weekdays around them: +3 to +8 %). Median factor 0.78–0.90 by date, range 0.14–1.42. Other dates unchanged.

### Growth extrapolation (`models/growth.py`)
- **Finding.** In the lag120_prod backtest every day type is under-forecast at network level (median of origin-dates, ensemble): JOHV −4 %, JOVS −5 %, SAHV −7 %, SAVS −7 %, DIJFP −8 %; Sundays alone −8 % (LightGBM −9 %). The Sunday excess was largest in 2024 – mid 2025 (monthly −10 to −18 %) and small since 2025-09.
- **Cause.** Weekend traffic grows faster than weekday traffic (711 stations present 2022–2026, school terms, no public holidays): Sunday / weekday 0.45 (2024 H1) → 0.49 (2025 H1) → 0.53 (2026 H1); Saturday / weekday 0.66 → 0.73 → 0.75. Trees do not extrapolate `t_days` past the training data and the data are ~4 months old at the issue date, so faster-growing day types fall further behind.
- **Rule.** Per weekday class (Mon–Fri, Sat, Sun), at the cutoff c: g = mean daily network total over [c − 182 d, c) / the same over the 182 days 364 d earlier (public holidays and flagged days out; stations with data on ≥ half the days of both windows). LightGBM × g^((date − c) / 364); the ensemble stays mean(corrected LightGBM, TFT) (TFT already follows part of the growth). Applied to the production rows and to the calibration log (each origin at its own cutoff, data before it only), so bands and special-day factors are calibrated on corrected forecasts. `lgbm` = corrected, `lgbm_raw` = model output, `growth` = factor; `[forecast] growth_window = 0` turns it off.
- **Validation** (rolling, 24 origins, special days out): ensemble WAPE 0.1056 → 0.1014 (origins 2025-06+: 0.0994 → 0.0965); LightGBM 0.1228 → 0.1126; better on 18 / 24 origins; Sunday network bias −8.7 % → −2.6 %. Weak spot: origins 2026-03..05, when weekend growth slowed: ensemble +1 % on average, worst +11 % (projecting last year's growth overshoots when it decelerates). 80 % band coverage unchanged (ensemble 0.810 vs 0.811, LightGBM 0.800 vs 0.805; relative width 0.377 vs 0.384). Special days with the corrected LightGBM: station WAPE 0.133 (0.130 before), network within ±5 %.
- **Rejected alternatives.** Post-hoc factor per day type from recent residuals (91–365 days): ~1 % WAPE on average but −17 % to +39 % by origin; per station × day type (shrunk): worse (0.110–0.120). LightGBM `linear_tree` (tweedie): diverges (origin 2025-12 WAPE 0.161 → 1.40 with λ 1, 0.40 with λ 1000).
- **First production run** (cutoff 2026-07-01): g = 1.054 / 1.091 / 1.125 (Mon–Fri / Sat / Sun); factors 1.02–1.07 over the forecast window; network +1.2 % on weekdays, +2.5 % on weekends; Sunday / JOHV 0.520 (0.511 before; 0.506 observed in the same weeks a year earlier). Special days Dec 24 / 25 / 31 / Jan 1: 4.42 / 2.24 / 3.08 / 2.27 M.

## Score (`idf-score build`, `make score` → `data/processed/typical_week.parquet`, `app/public/data/`)
v0 **Typical week view**: one **Crowding score** per **Place** × **Day type** × hour. Settings in
`config.toml` `[score]`.
- **Window**: the last 365 days of available data (first run: 2025-07-01 → 2026-06-30).
- **Usable station-days**: entries present, no quality flag (missing / low / high), a day type,
  and not a network-abnormal working day or Saturday (JOHV/SAHV with `network_ratio` < 0.8:
  strikes, snow). Same rule as the backtest. School-holiday and Sunday types are not filtered on
  `network_ratio`, since holiday weeks are low by nature.
- **Place days**: member Counting points are summed per date, only on dates where every member
  is usable.
- **Daily level**: mean entries per Place × Day type over usable days. Fewer than 8 days →
  `low_confidence` (none on the first run: min 9 days, SAVS).
- **Hourly profile**: mean of the last 4 quarterly profiles (2025Q3–2026Q2), hours a quarter
  does not report count as 0, renormalised to sum 1. A Place's profile is its members' profiles
  weighted by their daily level. Expected entries(hour) = daily level × share.
- **Reference level**: per Place, the 95th percentile of hourly entries on actual usable days
  (daily entries × that day type's profile), public holidays and bridge days excluded. All
  24 hours of every day enter the percentile, so typical weekday peaks score above 100
  (first run: each Place's highest hour scores 101–287, median 136).
- **Score** = 100 × expected / reference, rounded; bands quiet < 40 ≤ moderate < 70 ≤ busy
  < 100 ≤ very busy.
- **Best slots**: the 3 quietest hours starting 06:00–21:00, and for the busiest hour of
  06–12 h and of 15–21 h the quietest hour within ±2 h.
- **Scope**: Counting points served by a metro or RER line (`arrets-lignes` mode Metro or
  RapidTransit) or by T4. `arrets-lignes` stops are mapped to the ZdC through `arrets`
  (`IDFM:<arrid>`) or `zones-d-arrets` (`monomodalStopPlace:<zdaid>`). Transilien-only and
  other tram stations are hidden. T4 stops have no validation rows after 2017-06-30, so no T4-only
  station is shown.
- **ZdC aliases** (`[[score.zdc_aliases]]`): two in-scope reference ZdC have no validation rows
  because the data reports their entries under another ZdC: Châtelet - Les Halles (474151,
  RER A/B/D) is inside data ZdC 71264 (labels "CHATELET", "CHATELET-LES HALLES"), shown as
  "Châtelet – Les Halles"; Aéroport d'Orly 63284 (metro 14) → 63278 (Phase 2 stop-code remap).
  Their lines move to the data ZdC.
- **Places**: one per Counting point; merges only through `places.toml` (empty in v0).
- **Coordinates**: Lambert-93 (EPSG:2154) → WGS84 with the IGN inverse projection, checked
  against the portal's own geopoints (< 1e-7°).
- Line badges: active metro, RER, Transilien and tram lines from `referentiel-des-lignes`
  (web colours). Validations are per Counting point, never per line.

## Date forecasts in the app (`idf-score build` → `place.v2` files)
When `data/processed/forecast/CUTOFF/forecast.parquet` exists for the latest data cutoff, each
Place file is written as schema version 2 (`schemas/place.v2.schema.json`): every v1 field plus
`forecast` (`issue_date`, `data_end`, `dates`). Without a forecast the files stay v1. Code:
`score/dated.py`.
- **Place × date**: daily = sum of the members' `point`, only on dates where every member has a
  forecast and a day type.
- **Band** (`lo`, `hi`, 80 %): the Counting point's band for single-member Places. For merged
  Places it is null: summing member bands overstates the width, and a correct band needs the
  summed forecast in the calibration log (not built; no merged Place exists today).
- **Hours**: daily × the Place's typical-week profile of the date's day type (same profiles,
  **Reference level** and bands as the typical week). Score = round(100 × hourly / reference).
  A date whose day type has no profile for the Place is left out (none on the first run).
- **Delta** (`delta_pct`): daily forecast vs the typical-week daily level of the same day type.
  Hours share one profile, so the delta is the same for every hour and is stored once.
- **Special days** keep the day type's hourly profile (24 and 31 December probably end
  earlier): the hours of those days are less certain than the daily total.
- **Reasons**: the forecast's special day (24, 25, 31 December, 1 January), then public
  holiday, bridge day, school holidays (zone C) from the calendar sources.
- **Past dates**: dates before the build day (Europe/Paris) are dropped; the app must also hide
  dates that have passed since the build.
- **Size**: hours are stored as 24 integer scores per date (operating-day order). First run
  (built 2026-11-19): 538 Places × 84 dates (2026-11-19 → 2027-02-10), 22–25 KB per file
  (v1: ≤ 9 KB).

## Per-station accuracy (`idf-score build` → place.v2 `accuracy`, `app/public/data/accuracy.json`)
Code: `score/accuracy.py`; contract: `schemas/accuracy.v1.schema.json` and `$defs.accuracy` in
`schemas/place.v2.schema.json`. Without the backtest log the build still runs: place files get
no `accuracy` field and `accuracy.json` is not written (a stale one is removed).
- **Source**: the production-like forecast log, backtest variant `lag120_prod` (data cutoff =
  origin − 120 days, production weather), `deep/predictions.parquet`: one row per origin ×
  Counting point × date, scored rows only (same clean rows as the LightGBM backtest, stations
  with a TFT forecast). Model column `ens_lgbm_tft_seedavg` = mean(LightGBM, mean of the 3 TFT
  seeds' medians). This log predates the growth extrapolation and the special-day rule, so it
  measures the ensemble without them.
- **Error**: WAPE of the daily total = Σ|y − forecast| / Σy over every scored row of the Place.
  Origins are monthly with a 60-day horizon, so most dates are forecast by two origins; both
  rows count, as in the backtest report.
- **Scored days** = distinct dates with at least one scored row (not rows). **Fewer than 180
  scored days → `accuracy: null`** (owner rule). First run: 12 origins (2025-06-01 →
  2026-05-01), dates 2025-06-01 → 2026-06-29, at most 391 scored days per station.
- **Places with several Counting points**: y and forecast are summed per origin × date, only
  where every member has a scored row; WAPE and scored days are taken on those sums (none exist
  today).
- **No cap, no outlier removal.** Very large errors come from small stations, where a forecast
  that is off by a few hundred entries a day is a large share of the total. Worst case in the
  log: Champlan (T12 tram-train, ZdC 486959, ~55 entries a day, data ending 2025-12-13),
  WAPE 15.6 (1 560 %): LightGBM forecast 470 to 4 700 entries a day on average depending on the
  origin (TFT 29 to 61), and the ensemble keeps half of that error. It is outside the app's scope (no metro / RER), so it has
  no Place file and is not in the summary tiles either.
  Among the app's Places the largest errors are Magenta (45 %) and Haussmann Saint-Lazare
  (36 %), whose 2026 Q1 level jump is still being checked against the source.
- Places without a figure on the first run: Saint-Denis – Pleyel (179 scored days) and
  Villejuif – Gustave Roussy (no TFT forecast: under 365 clean days of history, so not in the
  ensemble log).
- **Summary (`accuracy.json`)**: the log (variant, lag, weather, model, origins, scored
  period, days since the last data day), the minimum-days rule, the number of Places with a
  figure and the median and 9th decile of their WAPE, and the tiles. The tiles use only the
  Counting points of the app's Places (metro + RER), so they describe the stations the app
  shows (owner decision, 2026-11-22: before, they covered every scored Counting point, T12
  and other non-app stations included; station 10.1 → 10.0 %, network 5.5 → 5.4 %, band
  0.806 → 0.821 on the first log):
  - `station_wape_pct`: WAPE over every scored row of the log (app Counting points);
  - `network_wape_pct`: WAPE of the daily network total (sum of scored stations per origin ×
    date);
  - `band.coverage`: share of scored rows inside the calibrated 80 % ensemble band
    (`deep/ensemble_bands.parquet`, `ens_conf_lo` / `ens_conf_hi`);
  - `special_days`: leave-one-year-out check of the special-day rule ("Special days" above),
    reproduced from the variant's LightGBM log (`origins/*/predictions.parquet`, warm-up +
    scored, growth-corrected as in production): factors from outcomes dated before 1 July of
    the latest Christmas season in the log, applied to that season's 24, 25, 31 December and
    1 January forecasts (clean rows); station-level WAPE of LightGBM × factor.
  A tile whose files are missing is left out; the app then hides it.
- **First run** (built 2026-11-19): 536 of 538 Places have a figure; median 8.4 %, 9th decile
  17.0 %. Tiles: 10.1 % per station-day, 5.5 % on the network total, 0.806 inside the 80 %
  band, 13.3 % on the special days of season 2025 (4 972 rows). These measure the daily total;
  the hourly split (typical profile of the day type) is not backtested.

### P(busy day) recalibration (`models/busy.py`, `idf-busy run` / `make busy`; not accepted)
**Question.** Can P(busy day) be made reliable enough to publish? Acceptance, on the
production-like log (variant `lag120_prod`, 12 scored origins, LightGBM growth-corrected as
in production, ensemble = mean(LightGBM, mean of 3 TFT seeds)): observed busy rate within
± 3 points of the mean predicted probability in every reliability bin with ≥ 500 rows,
overall and per season (DJF / MAM / JJA / SON); Brier skill vs "always 10 %" ≥ 0.23
(LightGBM) / 0.30 (ensemble).

**Thresholds** (`intervals.busy_threshold`, `method`):

| Method | Rule |
|---|---|
| `yearly` (backtest default) | Station p90 of clean days of the same day group (working day / Saturday / Sunday-holiday) in [c − 365 d, c) |
| `seasonal` | Same station and day group, clean days within ± 45 days of the target's day of year, all years before c (from `train_start`); fewer than 20 such days → the yearly p90. Each reference day × g ** ((target − day) / 364), g = the LightGBM growth rate of its weekday class at c (`growth.py`). Within the window, the p90 is taken on value / local level (median of the days within ± 10 days of year), then × the local level at the target's day of year: without it the window's seasonal slope leaks into the threshold (synthetic test: 0–16 % busy per month without, 10–13 % with) |

**Recalibration** (fitted at each origin on earlier origins' forecasts of clean days dated
in [c − 365 d, c), as the intervals): isotonic on p (`recalibrate_busy`); logistic regression
on logit(p) + horizon bucket indicators (`recalibrate_busy_logistic`; season and day group
can be added with `--context`; tried with a first version of the seasonal threshold (no local
level), it made the largest per-season gap worse: 0.31 → 0.37 LightGBM, 0.30 → 0.46 ensemble).

**Result** (`backtest/variants/lag120_prod/busy/report.md`):

| model | threshold | recalibration | observed rate | mean p | Brier skill | largest gap overall / per season | accepted |
|---|---|---|---|---|---|---|---|
| LightGBM | yearly | raw | 0.335 | 0.415 | 0.29 | 0.27 / 0.49 | no |
| LightGBM | seasonal | isotonic | 0.124 | 0.153 | 0.21 | 0.07 / 0.15 | no |
| LightGBM | seasonal | logistic | 0.124 | 0.148 | 0.20 | 0.15 / 0.22 | no |
| ensemble | yearly | raw | 0.333 | 0.379 | 0.35 | 0.20 / 0.52 | no |
| ensemble | seasonal | isotonic | 0.120 | 0.131 | 0.21 | 0.07 / 0.20 | no |
| ensemble | seasonal | logistic | 0.120 | 0.128 | 0.21 | 0.08 / 0.19 | no |

Skill is against "always 10 %", so it is not comparable across thresholds (the yearly
target's base rate of 33 % makes that reference weak).

- The seasonal threshold brings the busy rate from 33 % to 12 % overall, but not to
  8–12 % in every month (lgbm rows: 3 % in March, 30 % in July, 22 % in August) nor per
  origin (4 % to 26 %, warm-up origins included).
- The cause is the level, 4–10 months ahead and across reference years. The threshold
  compounds the growth factor known at c over the reference years and over the lag; network
  year-on-year growth of working days was +6–17 % per month in 2025 and +2–12 % in Jan–Jun
  2026, so the threshold's level is off by several percent when the regime changes, and the
  exceedance of a p90 is very sensitive to a few percent of level. The conformal residuals
  of earlier origins carry the previous regime: on 2026 origins (LightGBM roughly unbiased,
  forecast / actual 0.95–1.07) raw p is 0.11–0.19 and the observed rate 0.04–0.08;
  per-origin busy rate and network forecast bias are uncorrelated (r = −0.07).
- Removing each origin's network level bias with its own outcomes (a diagnostic, not a
  method) still leaves gaps of 0.10–0.33: station-level errors matter as much.
- More origins (monthly since 2023) were not run: the gaps are systematic (bins of 7 000–300 000
  rows), not noise.

Decision: P(busy day) stays out of the production forecast and the app. The code is kept to
re-run when more origins are available (`make busy`; ~5 min).

