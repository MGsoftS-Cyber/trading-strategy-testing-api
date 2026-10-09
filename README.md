# Trading Strategy Testing Platform API - v1.0.0

Historical USD crypto spot backtesting with **SMA long/cash** and **RSI reversion** strategies. Includes next-open execution, fractional positions, fees, adverse slippage, trade/round-trip ledgers, equity history, drawdown/return statistics, matched buy-and-hold benchmarks, saved experiment comparisons and optional expanding-window Ridge versus training-mean prediction tests.

**Runs locally using free libraries.** No exchange credentials, paid AI, wallet or cloud server is required. This is an API research baseline with Swagger, not an order-execution service or custom frontend. CSV/JSON ingestion is implemented; live feeds and scheduled jobs are future work.

## Local start - Python 3.12

From the extracted project root on Linux/macOS:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Windows: use `py -3.12 -m venv .venv` and `.venv\Scripts\Activate.ps1`, then the same pip/Alembic/Uvicorn commands. Compatible TA-Lib wheels include its native library; unsupported platforms may require upstream C installation.

Open http://localhost:8010/docs. Register with a valid email and 12-128 character password. Cookie login is automatic in a same-origin browser. Use the returned `csrf_token` in the `X-CSRF-Token` header on protected POSTs. Supply `Idempotency-Key` on workspace, dataset, backtest and demo creates: a new key per intended action, the same key/payload on retries.

In another terminal, from project root with the environment activated:

```sh
python scripts/demo_client.py --url http://127.0.0.1:8010
```

The client creates a random account, imports synthetic CSV, runs both strategies, compares saved reports, downloads every export, generates OpenAPI and logs out. It writes examples without printing its generated password.

## Docker with PostgreSQL

```sh
cp .env.example .env
# Edit POSTGRES_PASSWORD to a long random URL-safe value.
docker compose up --build
```

Open http://localhost:8090/docs. Run the client with `--url http://127.0.0.1:8090`. PostgreSQL is on a private container network with a persistent volume; the API is bound to localhost. Docker/PostgreSQL execution was not tested here because Docker is unavailable. Deleting the volume deletes stored experiments.

## Candle data

Exact CSV header:

```csv
date,market_id,open,high,low,close,volume
2025-01-01,bitcoin-usd,95000,97000,94000,96000,1234.5678
```

Use one declared venue per dataset, USD quote, UTC completed daily bars and base-asset volume. Maximum 20 markets, 730 daily candles per market, 15,000 rows overall. JSON prices/volume must be decimal strings (12 decimal places, 28 digits, maximum 10^15). Missing days, duplicates, invalid OHLC and current-day/future candles are rejected. The API checks structure; it cannot authenticate user-declared provider data.

POST `/api/v1/imports/preview` with `candles_csv`, `source`, `venue` and `coverage_end`; review the canonical result; then POST its `dataset` to `/api/v1/workspaces/{id}/datasets`. Preview is read-only and requires authenticated CSRF, but no replay key.

## Backtest request

```json
{
  "dataset_id": "returned-dataset-id",
  "market_id": "bitcoin-usd",
  "start_date": "2025-03-01",
  "end_date": "2025-06-01",
  "name": "SMA experiment",
  "strategy": "sma_cross",
  "initial_cash": "10000",
  "fee_rate": "0.001",
  "slippage_rate": "0.001",
  "fast_period": 10,
  "slow_period": 30,
  "rsi_period": 14,
  "rsi_low": 30,
  "rsi_high": 70,
  "enable_ml": true
}
```

POST to `/api/v1/workspaces/{id}/backtests`. Both range endpoints must exist for the chosen market; start must precede end. Earlier history warms the indicators, but account balances begin with initial_cash on the first simulated opening. A prior-day target can trigger a first-day entry. Later-than-end candles are excluded.

`strategy=sma_cross`: target long when SMA fast > slow, cash when fast < slow, retain prior state when equal. This is a target-state rule, so an already bullish state can enter at the requested start. `strategy=rsi_reversion`: target long when RSI <= low, cash when RSI >= high, retain state in between. TA-Lib owns RSI initialization; warm-up means no signal.

**Signals computed at day t's close fill only at day t+1's open.** The last-day signal has no fill inside the report. Buy fill=open*(1+slippage); sell fill=open*(1-slippage). Fees apply to executed notional on both sides. Entry quantity is rounded down to 10^-18 units so buying never borrows money. An unaffordable tick is logged as a skipped order. No leverage, shorts, stops or partial fills are simulated. Open final positions remain marked at the final close; no forced liquidation or hypothetical exit fees.

## Results and comparison

GET `/api/v1/backtests/{id}/report?format=` with `json`, `equity`, `trades`, `round_trips`, `signals` or `predictions`. JSON includes strategy and benchmark results; CSV exports cover the strategy and prediction audit rows. Monetary ledger values are decimal strings; statistics and prediction values are floating point. Negative numerical CSV fields remain parseable as numbers.

Performance: total return, 365-day CAGR, sample annualized volatility, zero-risk-free Sharpe, maximum close-sampled drawdown, exposure, fills, closed round trips, net win rate and profit factor. No closed trades -> null win rate; no closed losses -> null profit factor; zero/negligible volatility -> null Sharpe. Extreme CAGR exponent -> null with numeric_range reason. First-day costs are included by adding initial cash as the first equity baseline.

The benchmark enters at the same first opening with the same cash, fees and slippage and holds until the final mark. POST `/api/v1/comparisons` with 2-10 distinct `backtest_ids` from your account. Dataset, market, dates and numeric initial cash must match. Different cost rates are shown and flagged. This endpoint reads saved experiments and does not create a new report.

## Optional AI model comparison

The model predicts the next completed candle's **close/open - 1** from completed-bar features: daily return, SMA fast/slow gap, RSI fraction and historical 20-return volatility. At least 60 earlier labeled feature rows and 20 later test rows inside the requested range are required. The earliest full feature row is after all selected indicator lookbacks.

Every 20 test rows, refit a StandardScaler+Ridge(alpha=1, solver=svd) pipeline on an expanding earlier prefix. Compare against DummyRegressor(training mean). Training target dates must be at or before the first scoring decision date. Scaling uses training data only. Output fold boundaries, historical out-of-sample predictions, MAE, RMSE and directional accuracy. Predictions do not affect the strategy trades. Insufficient history disables only model comparison, not the backtest. No claim that Ridge beats the baseline or predicts future profits is made.

## Verification and scope

From backend:

```sh
ruff format --check app tests migrations
ruff check app tests migrations
pytest -q
alembic upgrade head
alembic check
```

51 tests cover accounting, timing, data validation, model chronology, comparison rules, security and snapshots. SQLite migration round-trip and schema comparison pass; real HTTP workflow passes. Docker/PostgreSQL runtime, live providers and public load tests are not verified. One upstream Starlette TestClient/HTTPX deprecation warning is documented; tests and the independent HTTP client pass.

The simulation assumes instant full fills at a configured adverse adjustment to the historical opening price. It does not reproduce liquidity, spread, market impact, minimum-order rules or real execution quality. Daily close drawdown misses intraday lows. Parameter selection after inspecting results can overfit. Do not treat synthetic example returns as investment evidence.

Public deployment requires HTTPS, secure cookies, configured origins, shared throttling, request-size limits, backups, retention and operational review. Local login throttling is in process.

## Project map

- `backend/app/signals.py`: completed-bar target state.
- `backend/app/simulation.py`: decimal cash, inventory, fills and P/L.
- `backend/app/metrics.py`: equity/return/risk statistics.
- `backend/app/prediction.py`: temporal regression comparison.
- `backend/app/engine.py`: complete saved experiment calculation.
- `backend/app/routes.py`, `models.py`, `services.py`: owner workflows and atomic replay.
- `backend/app/main.py`, `security.py`, `schemas.py`, `imports.py`: auth and request/data boundaries.
- `backend/tests/`, `migrations/`, `requirements.lock.txt`: verification, schema and pinned runtime.
- `scripts/demo_client.py`, `examples/`, `docs/`: reusable workflow, synthetic results and documentation.

MIT source license. Dependencies retain their own licenses.
