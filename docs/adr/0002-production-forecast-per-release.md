# Production forecast: one fit per IDFM release, LightGBM + TFT on a rented GPU

The production forecast is the mean of a LightGBM model and the average of 3 TFT seeds, with a conformal 80 % band. It is refitted once per IDFM data release (about quarterly), not on a calendar schedule: between releases the data does not change, so a refit would reproduce the same forecast. Each fit forecasts from the data cutoff (the day after the last published day) to cutoff + 225 days (~75 days of publication delay + ~90 days to the next release + 60 days), so one fit covers the time until the next release. The steps are one-shot CLI commands, each writing to `data/processed/forecast/<cutoff>/`; scheduling stays outside the code:

1. `make ingest clean features` (new quarter), then `idf-forecast lgbm` (LightGBM fitted on all clean data before the cutoff, forecasts issue date .. cutoff + 224).
2. `idf-deep export --production` → one input file → `notebooks/03_deep_colab.ipynb` on a GPU (Colab or Kaggle; 3 TFT fits).
3. `idf-forecast combine --deep <outputs>`: point = mean(lgbm, mean of seeds), band = conformal from the residuals of the production-like backtest (lag 120 days, production weather) dated in the 365 days before the cutoff. Stations without a TFT forecast (short history) get LightGBM alone with its own band. Without `--deep`, the whole forecast is LightGBM alone.

Future weather: observed where already downloaded, then day-of-year climatology (the backtest showed no loss vs observed weather). No P(busy day): not calibrated well enough.

## Considered Options

- **LightGBM alone:** no GPU step, but 12 % worse WAPE in the production-like backtest (0.115 vs 0.101 at lag 120).
- **Monthly refit:** same data between releases, so no gain; only a way to move the forecast window, which the 225-day horizon does once.
- **Weather-forecast feed for days 1-16:** an extra dependency for no measurable gain at daily level; can be added as a separate warning feature.

## Consequences

- Each release needs a manual GPU run (~45 min, 3 fits) until a scheduled GPU option is chosen.
- Forecast days 166-225 since the data are covered by the LightGBM lag-165 backtest (WAPE 0.117), not by a TFT backtest (TFT was backtested to 180 days).
- If IDFM publishes late and the issue date passes cutoff + 224, `idf-forecast lgbm` refuses to run: the app must fall back to the typical week.
