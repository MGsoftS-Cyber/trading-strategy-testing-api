# Trading Strategy Testing Platform

A detailed conception and programming guide for historical crypto strategy experiments. Includes a runnable Python API, exact simulation rules, editable source, tests, local setup and planning for every module.

| Included | Implementation |
| --- | --- |
| Strategies | SMA long/cash and RSI reversion target states |
| Execution | Previous close signal, next opening fill, fees and adverse slippage |
| Reporting | Equity, fills, round trips, benchmark and saved comparisons |
| Optional AI | Expanding-window Ridge versus training-mean prediction baseline |
| Operation | Free local libraries; SQLite; supplied Docker/PostgreSQL |
| Verification | 51 passing tests and a complete real HTTP exercise |

This is a research API with Swagger. It has no live wallet, exchange trading connection or custom dashboard. Data enters through CSV/JSON. Machine-learning predictions are evaluated separately and do not control strategy trades.

## Guide structure

Pages 2-6 explain conception, architecture and data. Pages 7-13 explain timing, trading math and performance. Pages 14-18 explain model testing, API integration and security. Pages 19-23 cover running, verification, planning and future design; page 24 maps source files and references.

# 01  Product conception

Question: "How would this rule have behaved on a specified historical market window, after the costs we choose?" The answer is a saved experiment, not a forecast of future profit.

| User | Application | Useful result |
| --- | --- | --- |
| Analyst | Compare rule variants on the same data/window | Net returns, drawdown and trade evidence |
| Finance manager | Explore turnover and cost sensitivity | Fees, slippage and benchmark difference |
| Developer | Integrate an experiment API into another application | Stable requests, saved snapshots and exports |

An account owns workspaces. A workspace owns datasets and backtests. The user uploads completed daily candles, picks one market and a date range, chooses a rule and costs, then saves a report. The report freezes data and settings so a later import cannot alter it.

## First-release scope

One USD-quoted crypto spot market per experiment, long or cash, no leverage or shorts. Fractional units are allowed, subject to a 10^-18 unit tick. Full fills are assumed at a configured adverse fraction of the historical open. The first release has no stop orders, depth model, funding costs, taxes or live broker operations.

Success means valid data, causal signals, consistent cash/position balances, visible costs, clear null statistics, protected ownership and reproducible reports. Profitability is not an acceptance criterion.

# 02  Application architecture

Architecture: Client -> FastAPI -> database; experiment engine -> Decimal simulation/metrics and optional temporal model comparison.

| Layer | Source | Role |
| --- | --- | --- |
| HTTP boundary | main.py, schemas.py, routes.py | Authentication, contracts, owned workflows and exports |
| Data / persistence | imports.py, models.py, services.py | Validation, immutable snapshots and atomic replay |
| Trading research | signals.py, simulation.py, metrics.py, engine.py | Target states, fills, ledger, benchmark and statistics |
| ML research | prediction.py | Chronological training and prediction evaluation |

The analytical modules are pure calculations over saved inputs. They do not send orders or open external market-data connections. HTTP endpoints compute synchronously in this baseline. A job queue, request-size limits and shared rate limiting belong to a scaled public deployment.

# 03  Data model and ownership

User owns Workspace and LoginSession. Workspace owns Dataset and Backtest. Backtest references Dataset. RequestRecord scopes replay to user and action.

| Table | Important contents |
| --- | --- |
| users / login_sessions | Email, Argon2 hash; opaque token digest, expiry and CSRF |
| workspaces | User foreign key, unique name per user, USD quote |
| datasets | Canonical candle JSON, source/venue, coverage, quality and fingerprint |
| backtests | Dataset/workspace keys, frozen inputs/results, engine version and timestamp |
| request_records | Unique user + scope + key, payload hash and saved response |

Read and export routes join through Workspace.user_id. A foreign identifier returns 404. Dataset and backtest update/delete endpoints are absent. Application immutability does not prevent a database administrator from editing stored rows; audit and retention controls are separate operational work.

# 04  Stack, languages and costs

| Technology | Purpose | Pinned version |
| --- | --- | --- |
| Python / FastAPI | Readable research code and typed HTTP API | 3.12 / 0.142.2 |
| Pydantic | Bounded decimal-string contracts and date checks | 2.13.5 |
| TA-Lib / NumPy | SMA, RSI and statistical arrays | 0.8.1 / 2.5.3 |
| scikit-learn | Pipeline, StandardScaler, Ridge and DummyRegressor | 1.9.1 |
| SQLAlchemy / Alembic | Persistent models and versioned database schema | 2.1.3 / 1.20.0 |
| Argon2 / HTTPX | Password hashes and real API client | 25.1.0 / 0.28.1 |
| SQLite / PostgreSQL | Local storage / supplied container alternative | SQLite runtime / PostgreSQL 17 |

All implemented calculations run locally without a paid AI account or server subscription. The project is MIT; dependencies retain individual licenses. Paid historical feeds, hosting or a managed database can add costs later. No paid provider is selected or required here.

## Why a small explicit simulator

A separate simulation.py makes the fill timing, quantity rounding, cost basis and final-mark policy easy to inspect and test. TA-Lib provides indicators and scikit-learn provides models; these libraries do not silently decide the trading execution rules. The simulator is deliberately limited to one simple position rather than claiming exchange-grade execution realism.

The complete requirements.lock.txt pins runtime dependencies. Compatible TA-Lib binary wheels installed successfully here; other platforms without a matching wheel may require its native C library.

# 05  Input contracts and CSV preview

| Contract | Requirement |
| --- | --- |
| Candles | UTC completed daily date; stable market ID; USD OHLC; base-unit volume |
| Validation | 0 < low <= open/close <= high; volume >= 0; no duplicate/missing days |
| Numbers | JSON decimal strings; OHLC/volume <= 10^15; 12 decimals, 28 digits |
| Dataset limits | 20 markets, 730 bars per market, 15,000 rows total |
| Experiment range | Exact start/end bars for selected market; start < end |
| Starting cash | Positive decimal string <= 10^12 |
| Costs | Fee and slippage decimal fractions from 0 through 0.05 |
| Indicators | Fast 2-99; slow 3-100; fast < slow; RSI 2-50; low < high |

```python
date,market_id,open,high,low,close,volume
2025-01-01,bitcoin-usd,95000,97000,94000,96000,1234.5678
```

POST /imports/preview accepts CSV text with source, venue and coverage_end. It writes no business record, returns canonical data and quality metadata, and uses the same DatasetInput validation as direct JSON imports. Review the result before committing it to a workspace.

Source and venue are user declarations. Structural validation cannot prove that candles are authentic, correctly resampled, accurately licensed or representative. Do not mix providers or volume units within one dataset.

# 06  Signal rules and state

| Rule | Target update | Between updates |
| --- | --- | --- |
| sma_cross | Fast SMA > slow -> long; fast < slow -> cash | Equal means retain state |
| rsi_reversion | RSI <= low -> long; RSI >= high -> cash | RSI between thresholds retains state |
| Warm-up | Indicator is unavailable -> no ready decision | Initial state is cash |

```python
# Actual SMA target-state code in signals.py
if fast[i] > slow[i]:
    target = 1
elif fast[i] < slow[i]:
    target = 0
# Equality retains the existing target.
```

A target is long or cash, not an order at the closing price. The simulator only buys when long is requested and no units are held, and only sells when cash is requested and units are held. Repeated long targets do not cause repeated purchases or daily rebalancing.

All earlier dataset history up to end_date warms the indicators and target state. Balances still begin with initial_cash at the requested start. If the previous day already had a long target, the experiment can enter at the first opening even if the crossing occurred before the window. This is why the SMA rule is described as a target-state rule.

RSI follows the pinned TA-Lib convention, including its initial smoothing. A numerical low RSI is a rule input, not proof that a market should recover. Last-day signals are reported but cannot fill after the experiment ends.

# 07  Execution timeline and causality

Timing: candle t closes -> compute target -> candle t+1 opening fill -> mark equity at t+1 close.

The indicator sees the completed close on day t. A fill using that same close would assume the analyst already knew its final value before placing an order. This implementation applies the target at the next recorded opening, so gaps between the signal close and execution open remain in the result.

Before start_date bars inform state but produce no positions or fees. After end_date bars are excluded before signal and model calculations. The last position is marked at the last close. A hypothetical next-day sale and its costs are not invented.

The opening-fill assumption is still an approximation: actual order timing, latency, available volume and price impact may differ. Configured slippage represents a chosen adverse adjustment, not an empirically calibrated execution guarantee.

# 08  Programming the decimal simulator

```python
# Actual buy calculation in simulation.py
execution = opening * (1 + slippage)
bought = (cash / (execution * (1 + fee))).quantize(
    UNIT_TICK, rounding=ROUND_DOWN
)
notional = bought * execution
cost = notional * fee
basis = notional + cost
cash -= basis
units = bought
```

The ledger uses Decimal with 60-digit local precision. Entry units round down to 10^-18 so the simulation cannot borrow cash through rounding. If the available cash cannot buy a tick, a skipped order is recorded and balances stay unchanged. Ledger outputs are decimal strings; indicators and statistics use float64.

## Selling and realized P/L

Sell execution = open x (1 - slippage). Net proceeds = units x execution x (1 - fee). Realized profit/loss = proceeds - stored entry cost basis. The basis includes the original buy fee. After selling, units and basis reset to zero, and the closed round trip stores entry cost, exit proceeds and net P/L.

At each close, market value = units x close; equity = cash + market value; unrealized P/L = market value - entry cost basis. Tests verify equity - initial cash = realized + unrealized P/L and nonnegative balances. Decimal precision and a model unit tick are explicit simulation choices, not real venue lot-size rules.

# 09  Worked fees and slippage example

Example: starting cash 1,000 USD; buy reference open 100; sell reference open 110; fee rate 1% on both sides; adverse slippage 2%. These are arithmetic demonstration assumptions, not recommended trading costs.

| Step | Calculation | Approximate value |
| --- | --- | --- |
| Buy execution | 100 x 1.02 | 102.00 |
| Affordable units | 1000 / (102 x 1.01), rounded down | 9.706853038245 |
| Buy notional | units x 102 | 990.099010 |
| Buy fee | buy notional x 0.01 | 9.900990 |
| Sell execution | 110 x 0.98 | 107.80 |
| Exit proceeds | units x 107.8 x 0.99 | 1035.934770 |
| Closed net P/L | net exit proceeds - entry basis | 35.934770 |

The buy fee applies to execution notional. Slippage affects the execution price first, so it also slightly changes the fee amount. slippage_cost separately reports units times the adverse price difference, but it is already embedded in the fills and must not be deducted from equity a second time.

The stored entry quantity retains its full 18-place tick precision; this table rounds values only for display. With open final units, unrealized P/L includes the paid entry fee through basis, while future exit costs remain uncharged.

# 10  Equity and performance definitions

| Metric | Implementation |
| --- | --- |
| Total return | final equity / initial cash - 1 |
| Daily return | current close equity / preceding equity - 1; first preceding value is initial cash |
| CAGR | (final/initial)^(365 / simulated days) - 1 |
| Drawdown | equity / running peak - 1; maximum reported as a positive loss fraction |
| Volatility | Sample standard deviation of daily returns x sqrt(365) |
| Sharpe | Mean daily return / sample std x sqrt(365); risk-free rate assumed zero |
| Exposure | Fraction of close marks with a positive position |
| Win rate | Positive net closed round trips / all closed round trips |
| Profit factor | Sum positive closed net P/L / absolute sum negative closed net P/L |

Initial cash is prepended to the equity sequence. Consequently, first-day entry costs affect both daily return and drawdown; a chart starting only after fees would otherwise hide that loss. Days include every completed daily bar inside the requested window.

No closed round trips gives a null win rate. No closed losses gives a null profit factor rather than infinity. Zero/negligible volatility gives null Sharpe. A CAGR exponent outside the supported numeric range gives null with a reason. A zero-P/L round trip is not a win.

The annualization convention is 365 calendar days for crypto. Short-window CAGR and Sharpe can be unstable. Drawdown samples closes and does not capture an intraday low between marks. These are descriptive measures for the chosen experiment.

# 11  Benchmark and experiment comparisons

Each report includes a buy-and-hold benchmark: enter at the first simulated open with the same initial cash, fee and slippage, then retain units through the final close. The benchmark and strategy use the same price window, quantity tick and final-mark policy.

| Comparison rule | Purpose |
| --- | --- |
| Same dataset_id | Keep input provenance and candle snapshot identical |
| Same market and date range | Avoid changing the opportunity window |
| Same numeric initial cash | Keep capital scale consistent; decimal representations may differ |
| Distinct saved IDs, 2-10 | Prevent comparing a report to itself or excessive fan-out |
| Costs visible in every row | Permit documented cost-sensitivity runs; flag varying assumptions |

POST /comparisons retrieves saved experiments owned by the caller and returns returns, drawdowns, Sharpe, fill counts, fees and each matched benchmark. It does not recompute reports or create a new stored experiment. Different fee/slippage settings are intentionally allowed and explicitly flagged.

Excess total return is strategy total return minus its cost-matched benchmark return. It is not a risk-adjusted alpha estimate. A larger historical return is not automatically preferable: turnover, drawdown, cost assumptions and parameter selection must remain visible.

# 12  Actual synthetic experiment results

Synthetic equity chart: initial capital baseline plus SMA, RSI and cost-matched buy-and-hold daily equity curves.

| Experiment | Net return | Max drawdown | Fills | Closed rounds |
| --- | --- | --- | --- | --- |
| sma_cross | -37.58% | 38.39% | 8 | 4 |
| rsi_reversion | 4.40% | 6.14% | 1 | 0 |

These are the executed 130-day demonstrations with 10,000 USD starting cash, 0.1% fee and 0.1% adverse slippage. The matched benchmark returned approximately 1.44%. Both model comparisons contain 90 historical test predictions.

The SMA strategy loses money in this artificial sequence. The RSI example has one open position and no closed round trip, so its win rate is unavailable. The examples test mechanics; choosing the displayed winner after seeing results would not establish future predictive performance.

# 13  Optional prediction-model research

prediction.py evaluates a separate supervised task: predict the next completed candle's close/open - 1 from features known at the current completed close. Ridge predictions do not create or modify simulated trades.

| Component | Definition |
| --- | --- |
| Features | Current daily return; SMA fast/slow - 1; RSI/100; sample 20-return volatility |
| Target | Next candle close / next candle open - 1 |
| Training minimum | 60 earlier complete labeled feature rows |
| Testing minimum | 20 later scoring rows with target dates inside the requested range |
| Models | Training-only StandardScaler + Ridge(alpha=1, solver=svd); DummyRegressor(training mean) |
| Refit schedule | Expanding training prefix; refit every 20 test rows |
| Outputs | Fold chronology, predictions, actual returns, MAE, RMSE and direction accuracy |

The close/open target describes the next candle's intraday daily-bar return, while the strategy simulator can hold through overnight gaps for many days. These are different tasks. A lower model error cannot be interpreted directly as a better trading return.

Insufficient history or unsupported numeric ranges return an unavailable model status while the rule-based backtest continues. A flat target series can still be evaluated; finite zero errors are valid and do not require a misleading R-squared claim.

# 14  Walk-forward timing and code

```python
# Actual fitting block in prediction.py
train = rows[:first]
x = np.array([r["features"] for r in train])
y = np.array([r["actual"] for r in train])
assert train[-1]["target_date"] <= rows[first]["decision_date"]
with threadpool_limits(limits=1):
    ridge = make_pipeline(
        StandardScaler(), Ridge(alpha=1.0, solver="svd")
    ).fit(x, y)
    dummy = DummyRegressor(strategy="mean").fit(x, y)
```

For a first scoring decision on day t after close, the latest permissible training target is day t's completed close/open return. The prior training feature row is from day t-1. Its label is known by day t close, so it can enter training without using day t+1 data.

The fitted model scores the next block of at most 20 later decisions without refitting inside that block. The next fold expands training to the prefix before its first decision. The scaler is fitted inside the pipeline on training features only. No shuffled train/test split or full-history normalization is used.

Each fold records training decision dates, latest target date and test decision boundaries. Tests compare unchanged prefixes when more future data is added and verify that altering later candles cannot change earlier predictions. Model parameters are fixed; no tuning on the test rows is claimed.

# 15  Understanding model comparison scores

| Score | Formula / interpretation |
| --- | --- |
| MAE | Mean absolute predicted-minus-actual return; lower is smaller historical error |
| RMSE | Square root of mean squared return error; emphasizes large misses |
| Direction accuracy | Fraction where predicted > 0 matches actual > 0; zero is treated as nonpositive |
| Training-mean baseline | Predict the mean of training labels for every row in the current fold |
| Evaluation rows | Same historical scoring rows for Ridge and baseline |

| Model | MAE | RMSE | Direction match |
| --- | --- | --- | --- |
| ridge | 0.004981 | 0.021957 | 95.6% |
| training_mean | 0.008894 | 0.021213 | 43.3% |

The values above are computed from the supplied synthetic SMA-feature experiment. Errors are return fractions: 0.01 means one percentage point of return. The score table is not a confidence estimate or a claim that Ridge is generally superior. Different indicator parameters can change which features and scoring rows are available.

Before a predictive product launch, use licensed representative data, preserve an untouched final period, compare simple baselines and document uncertainty. Repeatedly selecting the best rule or parameter after viewing many tests is a separate source of overfitting even when each individual fold is causal.

# 16  API contracts and exports

| Method / route | Purpose |
| --- | --- |
| POST /api/auth/register, /login; GET /session | Create account / authenticate / get CSRF session |
| POST /api/auth/logout | Revoke current session |
| GET/POST /api/v1/workspaces | List/create owned research collections |
| POST /api/v1/imports/preview | Validate CSV without committing |
| GET/POST /api/v1/workspaces/{id}/datasets | Read/create immutable market snapshots |
| POST /api/v1/workspaces/{id}/backtests | Save one strategy experiment |
| GET /api/v1/backtests; /backtests/{id} | List latest 100 or retrieve one saved report |
| GET /api/v1/backtests/{id}/report | Export json/equity/trades/round_trips/signals/predictions |
| POST /api/v1/comparisons | Compare 2-10 compatible saved experiments |
| POST /api/v1/demo | Generate synthetic data in an empty workspace catalog |

Create routes need Idempotency-Key. Authenticated POST requests need X-CSRF-Token plus the session cookie. Preview and comparison do not create persistent records and require no replay key. CSV exports cover strategy audit rows and model predictions; the JSON report additionally includes the benchmark and all metadata.

Validation returns 422, authentication 401, CSRF/origin failures 403, unknown or foreign records 404, replay conflicts 409 and login throttling 429. Validation errors show field paths/messages without echoing password values. The supplied OpenAPI JSON is generated by the running server.

# 17  Authentication and atomic storage

Argon2 hashes passwords. A browser holds an HttpOnly, SameSite=Lax opaque session cookie; the database stores its digest, expiry and CSRF token. COOKIE_SECURE enables Secure for HTTPS. Supplied browser Origin must be allowed, and authenticated writes compare the CSRF header in constant time.

## Atomic replay

```python
# Business write and replay receipt share one commit.
result = work()
db.add(RequestRecord(
    user_id=user.id, scope=scope, key=key,
    payload_hash=fingerprint, response=result
))
db.commit()
return result
```

A repeated key and identical payload returns the saved response; the same key with changed settings returns 409. A unique user/scope/key constraint protects concurrent receipts. Work flushes but does not independently commit; validation failures cannot leave a partially saved backtest.

A saved backtest contains the chosen dates, rule/costs, full dataset snapshot, source/venue, results, engine version and package versions. Export retrieves saved values and never reruns an old experiment with today's prices. Ownership is checked on retrieval and comparison, not only creation.

The local authentication limiter is in process. Public multi-worker deployment needs shared throttling, HTTPS, trusted proxy configuration, request-size limits, backups, retention and operational review. These are launch tasks, not features claimed as already deployed.

# 18  Local use and reusable client

```python
# Project root, Linux/macOS
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8010

# Another terminal, project root, activated environment
python scripts/demo_client.py --url http://127.0.0.1:8010
```

Open http://localhost:8010/docs. Register a valid email and 12-128 character password. Browser cookies are automatic on the same origin; paste the returned csrf_token into the X-CSRF-Token header for protected requests. Use a fresh replay key for each intended create.

The supplied HTTPX client creates a random account, downloads synthetic candles, writes CSV, previews/imports it, runs SMA and RSI, compares saved reports, exports every format, retrieves OpenAPI and logs out. It uses trust_env=False for predictable local access and does not print its generated password.

On Windows, create the environment with py -3.12 and activate .venv\Scripts\Activate.ps1; the remaining commands are the same. The default SQLite file is backend/strategy.db when launched from backend. Alembic explicitly creates tables before the server starts.

# 19  Docker and operational deployment

```python
# From project root
cp .env.example .env
# Set POSTGRES_PASSWORD to a long random URL-safe value.
docker compose up --build
# Swagger: http://localhost:8090/docs
python scripts/demo_client.py --url http://127.0.0.1:8090
```

Docker installs the complete pinned runtime into Python 3.12, runs as a nonroot user, applies Alembic and launches Uvicorn. Compose waits for PostgreSQL 17 health, exposes the API only on localhost:8090 and retains database data in a named volume. PostgreSQL is not published to a host port.

| Before public launch | Reason |
| --- | --- |
| HTTPS + secure cookie/origins | Protect sessions outside localhost |
| Shared throttling + proxy/body limits | Bound abuse and large import requests |
| Analysis queue + quotas | Control concurrent CPU-heavy experiments |
| Backups + restore rehearsal | Protect datasets and saved research |
| PostgreSQL/container validation | Exercise the actual deployment database and image |
| Logging + retention policy | Diagnose failures and manage account/data lifecycle |

Docker is unavailable in the creation environment, so container/PostgreSQL execution was not tested. Local Python/SQLite, migrations and real HTTP were tested. Do not delete the named volume unless intentionally removing saved data. No external hosting service is necessary for local use.

# 20  Verification and limitations

| Check | Result |
| --- | --- |
| Automated suite | 51 tests pass; accounting, timing, signal states, contracts, chronology and security |
| Simulation invariants | Nonnegative balances, P/L identity, fees/slippage, rounding, no repeated entry and final marks |
| Model chronology | Earlier known labels, prefix invariance and score arithmetic verified |
| API workflows | Two strategies, matching comparisons, varied costs, six export formats and logout pass |
| Real demo | 360 dataset candles; 130-day experiments; SMA 8 fills, RSI 1 fill; 90 test predictions each |
| Schema / lint | SQLite upgrade/downgrade/re-upgrade/schema check; Ruff passes |
| Document review | PDF rendered for visual review; code, diagrams, tables and chart checked |
| Not executed | Docker/PostgreSQL runtime, public load tests and live-provider ingestion |

One upstream Starlette warning recommends HTTPX2 for TestClient. Current tests and the separate real HTTPX client pass. The warning is documented, not silently suppressed.

A backtest is conditional on prices and assumptions. The simulator uses full fills, configured slippage and fractional units; it does not model spread, depth, impact, minimum notional, order rejection, outages, taxes or derivatives. Close-only drawdown misses intraday losses. Synthetic returns and model errors are not evidence of future investment performance.

# 21  Development plan by module

| Module / estimate | Programming sequence | Acceptance criterion |
| --- | --- | --- |
| 1. Contracts/imports
2 days | Define calendar/units; validate OHLC; preview CSV; canonical snapshots | Bad data rejected; preview/save round-trip |
| 2. Auth/ownership
2 days | Accounts, sessions, CSRF, workspace and owner checks | Foreign records inaccessible |
| 3. Signals/timing
2 days | TA-Lib indicators; persistent target states; prior-close lookup | Warm-up and no same-close fills verified |
| 4. Decimal simulation
3 days | Buy/sell sizing, fees, basis, ledger, open marks, tick skips | Cash >= 0; equity/P&L identity; cost examples pass |
| 5. Metrics/benchmark
2 days | Baseline equity, null cases, closed statistics and buy/hold | First costs included; fair matched benchmark |
| 6. ML evaluation
3 days | Temporal feature/target rows; expanding fit; mean baseline; folds/scores | No future leakage; exports match errors |
| 7. API/storage/exports
2 days | Atomic replay, saved results, comparisons and CSV/JSON | Retry does not duplicate; comparisons enforce shared inputs |
| 8. Delivery/review
2 days | Migrations, client, Docker, documentation and target validation | Real HTTP and target database checks pass |

These are estimates for one experienced developer building this scope from scratch: 18 working days plus 2-3 days for integration and independent review. The supplied baseline is implemented and locally tested. Target-container and public operational work remain separate acceptance tasks; production scale depends on requirements.

# 22  Application design and future work

## Proposed future dashboard

A workspace header identifies the dataset, venue, coverage and experiment window. An experiment form exposes rule parameters, cash, fee and slippage together. Results show strategy versus benchmark equity, drawdown, fill ledger, round trips and cost totals. An independent model panel shows prediction errors, baseline scores and fold dates without labeling them trading confidence.

| Stage | Design / engineering | Completion check |
| --- | --- | --- |
| Dashboard | Import preview, parameter form, equity/drawdown plots, audit tables and comparisons | Render saved API results faithfully, including null and open-position values / 4-6 days |
| Live ingestion | Allowlisted read-only provider, UTC normalization, retries and provenance | Discard incomplete bars and reconcile licensed units / 3-5 days |
| Execution research | Calibrated spread/impact, venue lot/minimum rules and missing-fill behavior | Independent execution examples before realism claims / separately scoped |
| Queued experiments | Jobs, progress, quotas and notifications | Idempotent processing and owner-scoped job results / 3-4 days |
| Predictive research | Real-data holdout, parameter controls, uncertainty and drift | Untouched final evaluation and documented baseline comparison / separately scoped |

The current ZIP supplies Swagger, not these custom screens. Paid market data or hosted AI explanations can be considered later with licensing and budget controls. Neither is needed for this local API. A future live-trading system would require a separate execution design; connecting a wallet is not a shortcut from backtesting to reliable trading.

# 23  Source map and references

| File / directory | Read it for |
| --- | --- |
| schemas.py + imports.py | Input rules, dates, units and CSV preview |
| signals.py | SMA/RSI target states from completed candles |
| simulation.py | Decimal entries/exits, ledger and final marking |
| metrics.py | Equity returns, drawdown, Sharpe and null cases |
| prediction.py | Expanding-window regression and baseline comparison |
| engine.py | Selected-window orchestration and methodology |
| routes.py + services.py + models.py | Owner workflows, snapshots, replay and comparisons |
| main.py + security.py | Account/session, CSRF, origins and safe errors |
| tests/ + migrations/ + scripts/demo_client.py | Verification, schema and real HTTP example |
| examples/ + docs/ | Synthetic audit outputs, OpenAPI and editable guide |

## Primary documentation checked 06 October 2026

TA-Lib Python: https://github.com/TA-Lib/ta-lib-python

TA-Lib catalog: https://ta-lib.org/functions/

Ridge: https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html

DummyRegressor: https://scikit-learn.org/stable/modules/generated/sklearn.dummy.DummyRegressor.html

Chronological splitting: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

The implementation uses explicit expanding blocks rather than the TimeSeriesSplit class; that reference explains why chronology matters. Model and execution semantics in this guide describe the supplied source. Consult upstream platform installation and license instructions before redistribution.
