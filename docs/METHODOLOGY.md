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
