# Verification - 06 October 2026

## Executed

- Python 3.12.14 with complete pinned runtime dependencies.
- 51 tests passed. Covers next-open timing, last-signal handling, fees/slippage, fractional sizing, nonnegative balances, P/L identity, no repeated entry, no forced end liquidation, tick skips, first-day drawdown/costs, closed-trade statistics and both strategies.
- Data and contracts: decimal strings, cost bounds, period order, OHLC, duplicates/gaps, coverage and dates.
- Optional models: expanding-window chronology, training labels available before scoring, unchanged prefix predictions, mutation of future rows, disabled/short-history behavior and score arithmetic.
- API/security: ownership, replay/conflicts, CSRF, origins, session login/logout, validation hygiene, failed writes, comparison compatibility, equivalent cash representations and changed-cost flags.
- Ruff formatting/lint passed for app/tests/migrations and the real HTTP client.
- SQLite Alembic upgrade, downgrade on an empty isolated database, re-upgrade and schema comparison passed.
- Uvicorn + real HTTPX workflow passed: registration, synthetic demo, CSV preview/import/deduplication, two saved backtests, comparison, six export formats, Swagger/OpenAPI and logout.
- Demo: 360 dataset candles; 130 simulated days each; SMA 8 fills and 4 closed rounds; RSI 1 fill and no closed rounds; 90 historical test predictions per model comparison.
- Exported monetary CSV values parsed as decimals; each report serializes with allow_nan=False.
- PDF: 24 pages rendered and visually checked; no blank pages, clipped tables, or overlapping chart labels.
- ZIP files verified byte-for-byte against source; environments, databases, caches and secrets excluded.

## Limits

Docker is unavailable here: Docker/PostgreSQL runtime was not executed. Public load tests, actual provider feeds and external deployment were not performed. This release imports CSV/JSON, has Swagger but no custom dashboard, and has no live exchange execution.

The synthetic results verify mechanics, not financial predictability. Full fills, configured slippage, fractional units and close marks are simulation assumptions. No leverage, shorts, spread/depth/impact model, venue minimum notional, tax or funding accounting is included.

One upstream Starlette TestClient deprecation warning recommends HTTPX2. Current tests and the independent HTTPX client pass; the warning is documented rather than suppressed.
