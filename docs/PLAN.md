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
