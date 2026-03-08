# Bitcoin Node Cost & Performance Optimizer (MVP)

MVP for monitoring Bitcoin-node-like workloads, estimating monthly cloud cost, and generating optimization recommendations.

## Stack
- FastAPI + SQLAlchemy (SQLite local / PostgreSQL optional)
- Smart collector (bitcoind RPC with mock fallback)
- Benchmark runner (idle / initial-sync / high-rpc)
- Terminal-style dashboard with simulation and action engine
- Docker Compose (optional)

## Environment
### API (`api/.env.example`)
- `APP_ENV` = `development` | `test` | `production`
- `DATABASE_URL` (SQLite local by default)
- `READ_API_KEY` (read/simulation/action endpoints)
- `WRITE_API_KEY` (metric ingest/reset endpoints)
- `ALLOWED_ORIGINS` (comma-separated CORS allowlist)

In `production`:
- `DATABASE_URL` must not be SQLite
- `READ_API_KEY` is required and should be >= 16 chars
- `WRITE_API_KEY` is required and should be >= 16 chars
- `ALLOWED_ORIGINS` must be explicit origins (no `*`)

### Collector (`collector/.env.example`)
- `API_URL`
- `API_WRITE_KEY` (set this to match API `WRITE_API_KEY`)
- `INTERVAL_SECONDS`
- `COLLECTOR_MODE` = `auto` | `mock` | `rpc`

## Quick start (recommended: local, no Docker)
1. Install local API deps:
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
3. Start collector:
   ```bash
   set API_URL=http://127.0.0.1:8765
   set API_WRITE_KEY=dev-write-key
   python collector/mock_collector.py
   ```
4. Start dashboard server:
   ```bash
   python -m http.server 8899 -d dashboard
   ```
5. Open: http://127.0.0.1:8899
6. In dashboard, enter `READ_API_KEY` (or open with `?read_api_key=dev-read-key`).

## Action Engine
Generate executable change plans with rollback steps.

Manual API example:
```bash
curl -X POST http://127.0.0.1:8765/actions/plan \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-read-key" \
  -d '{"maintenance_window":"off_peak","include_high_risk":false}'
```

Response includes:
- prioritized actions (`P1/P2/P3`)
- risk levels (`low/medium/high`)
- apply steps
- rollback steps
- expected monthly savings

## Main endpoints
- `POST /metrics` (`WRITE_API_KEY`)
- `DELETE /metrics/reset` (`WRITE_API_KEY`)
- `GET /metrics/latest` (`READ_API_KEY`)
- `GET /metrics/recent?limit=40` (`READ_API_KEY`)
- `GET /summary` (`READ_API_KEY`)
- `POST /simulate` (`READ_API_KEY`)
- `POST /actions/plan` (`READ_API_KEY`)
- `GET /health` (public)

## Benchmarks
Run benchmark with split keys:
```bash
python benchmarks/run_benchmarks.py --api-url http://127.0.0.1:8765 --read-key dev-read-key --write-key dev-write-key
```

## Basic test run
```bash
cd api
python -m unittest discover -s tests -p "test_*.py" -v
```
