# Bitcoin Trend

MVP for ingesting Bitcoin price candles, extracting trend features, and predicting whether the next move is more likely to go up, down, or sideways.

## Stack
- FastAPI + SQLAlchemy
- Collector modes for synthetic candles or real BTC-USD market candles
- Trend engine based on moving averages, momentum, volatility, and volume confirmation
- Browser dashboard for price trend and directional forecast
- Docker Compose and CI

## Environment
### API (`api/.env.example`)
- `APP_ENV` = `development` | `test` | `production`
- `DATABASE_URL`
- `READ_API_KEY` for summary and prediction endpoints
- `WRITE_API_KEY` for candle ingestion/reset endpoints
- `ALLOWED_ORIGINS` as a comma-separated CORS allowlist

In `production`:
- `DATABASE_URL` must not be SQLite
- `READ_API_KEY` and `WRITE_API_KEY` should each be at least 16 characters
- `ALLOWED_ORIGINS` must be explicit origins, not `*`

### Collector (`collector/.env.example`)
- `COLLECTOR_MODE` = `mock` | `market`
- `API_URL`
- `API_WRITE_KEY`
- `INTERVAL_SECONDS`
- `TREND_MODE` = `auto` | `bull` | `bear` | `sideways`
- `START_PRICE_USD`
- `BASE_VOLUME_BTC`
- `VOLATILITY_PCT`
- `CANDLE_INTERVAL_MINUTES`
- `BOOTSTRAP_CANDLES`
- `MARKET_API_BASE_URL`
- `MARKET_PRODUCT_ID`
- `MARKET_SOURCE`

## Quick start
1. Install API dependencies:
   ```bash
   pip install -r api/requirements-local.txt
   ```
2. Start API:
   ```bash
   set READ_API_KEY=dev-read-key
   set WRITE_API_KEY=dev-write-key
   set ALLOWED_ORIGINS=http://127.0.0.1:8899,http://localhost:8899
   uvicorn main:app --app-dir api --host 127.0.0.1 --port 8765 --reload
   ```
3. Start the collector in mock mode:
   ```bash
   set COLLECTOR_MODE=mock
   set API_URL=http://127.0.0.1:8765
   set API_WRITE_KEY=dev-write-key
   set TREND_MODE=auto
   set BOOTSTRAP_CANDLES=72
   python collector/collector.py
   ```
4. Or start the collector in real-market mode with Coinbase BTC-USD candles:
   ```bash
   set COLLECTOR_MODE=market
   set API_URL=http://127.0.0.1:8765
   set API_WRITE_KEY=dev-write-key
   set INTERVAL_SECONDS=60
   set CANDLE_INTERVAL_MINUTES=60
   set BOOTSTRAP_CANDLES=72
   set MARKET_API_BASE_URL=https://api.exchange.coinbase.com
   set MARKET_PRODUCT_ID=BTC-USD
   python collector/collector.py
   ```
5. Start the dashboard:
   ```bash
   python -m http.server 8899 -d dashboard
   ```
6. Open `http://127.0.0.1:8899` and enter `dev-read-key`.

Notes for market mode:
- `CANDLE_INTERVAL_MINUTES` currently supports `1`, `5`, `15`, `60`, `360`, and `1440`
- The API ingests live candles idempotently by `source + timestamp`, so re-polling the current market bucket updates the same candle instead of duplicating rows
- `market_collector.py` uses Coinbase Exchange public candles for BTC-USD and does not require a Coinbase API key for read-only market data

## Main endpoints
- `POST /prices` with `WRITE_API_KEY`
- `DELETE /prices/reset` with `WRITE_API_KEY`
- `GET /prices/latest` with `READ_API_KEY`
- `GET /prices/recent?limit=72` with `READ_API_KEY`
- `GET /trend/summary?lookback=48` with `READ_API_KEY`
- `POST /predict` with `READ_API_KEY`
- `GET /signals/recent?limit=8` with `READ_API_KEY`
- `GET /signals/stats?limit=20` with `READ_API_KEY`
- `GET /signals/performance?limit=60` with `READ_API_KEY`
- `GET /reads/multi` with `READ_API_KEY`
- `GET /backtest/report?lookback=48&forecast_horizon=6&sample_size=24` with `READ_API_KEY`
- `GET /backtest/export.csv?lookback=48&forecast_horizon=6&sample_size=24` with `READ_API_KEY`
- `GET /health`

`/signals/recent` returns the recent prediction scorecard, including whether each saved signal is still open or later resolved as right, wrong, or flat.
`/signals/stats` returns a lightweight recent-edge summary, including hit rate, resolved reads, open reads, and a short user-facing summary of how the latest sample is performing.
`/signals/performance` returns recent resolved performance split by bias and setup quality so the action card can show which reads have been working better lately.
`/reads/multi` returns three user-facing action reads: `Fast`, `Core`, and `Bigger Picture`.
`/predict` and `/reads/multi` also return trader-facing action fields for `entry`, `invalidation`, `target`, and `risk_reward_ratio`.
`/signals/recent` now stores those same trade-plan fields so the scorecard can keep the original setup context instead of only the directional bias.
`/predict`, `/signals/recent`, and `/backtest/report` also expose `model_version` and `run_id` so each saved read can be tied back to the exact engine revision that produced it.
`/backtest/report` runs a recent walk-forward evaluation on historical candles and returns hit rate, edge, drawdown, confidence, and recent backtest runs so the UI can show whether the engine is earning trust.
Most read endpoints accept an optional `source` query param so the dashboard can stay scoped to one feed instead of mixing `mock` with live market data.
The default champion engine is still `heuristic`. An experimental challenger can be enabled at process start with `SIGNAL_ENGINE=ml_challenger`; it uses a pure-Python logistic baseline trained only on prior windows from the same candle stream.
`/backtest/report` now also includes a `shadow_comparison` block so the dashboard can compare the heuristic champion against the ML challenger on the same recent windows.
The same block carries explicit promotion gates: global sample size, hit-rate edge, cumulative edge, drawdown penalty, walk-forward window consistency, plus separate `trend` and `sideways` regime checks. The dashboard backtest view now breaks those two regimes out into their own panel so you can see where the challenger is actually winning or leaking.
The dashboard action card also supports local `saved setups`, so a user can keep promising reads in the browser and quickly recheck the same market lens later without going through audit details.
The dashboard also supports local `bias flip alerts`: you can keep them in-page only, or request browser notification permission and get a popup when the live read changes direction for the same source/lookback/horizon.
The dashboard also supports a local `user mode` switch: `conservative`, `balanced`, and `aggressive` all use the same backend read, but they change how the action card frames the next step for different trading styles.
The dashboard now also shows a short dismissible onboarding note so a new user sees, in one pass, what the page helps with and what it does not do.

Example prediction request:
```bash
curl -X POST http://127.0.0.1:8765/predict \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-read-key" \
  -d '{"lookback":48,"forecast_horizon":6}'
```

## Benchmarks
Run the API benchmark:
```bash
python benchmarks/run_benchmarks.py --api-url http://127.0.0.1:8765 --read-key dev-read-key --write-key dev-write-key
```

Run the offline benchmark:
```bash
python benchmarks/run_offline_benchmarks.py
```

## Local Preview
- `start-dev.ps1` now boots the preview stack with live `BTC-USD` market candles by default.
- To force the preview back to synthetic mode, set `PREVIEW_DATA_MODE=mock` before running the script.
- Optional preview env overrides:
  - `PREVIEW_MARKET_PRODUCT_ID` (default `BTC-USD`)
  - `PREVIEW_CANDLE_INTERVAL_MINUTES` (default `15`)
  - `PREVIEW_BOOTSTRAP_CANDLES` (default `192`)
  - `PREVIEW_POLL_SECONDS` (default `30`)

## Test
```bash
cd api
python -m unittest discover -s tests -p "test_*.py" -v
```
