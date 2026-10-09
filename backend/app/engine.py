"""Historical experiment orchestration; no wallet or order routing."""

from importlib.metadata import version
from .signals import build_signals
from .simulation import simulate
from .metrics import measure
from .prediction import compare

ENGINE_VERSION = "backtest-1.0.0"


def evaluate(inputs):
    start = inputs["start_date"]
    end = inputs["end_date"]
    if end > inputs["coverage_end"]:
        raise ValueError("end_date exceeds dataset coverage_end.")
    bars = sorted(
        [r for r in inputs["candles"] if r["market_id"] == inputs["market_id"] and r["date"] <= end],
        key=lambda r: r["date"],
    )
    dates = {r["date"] for r in bars}
    if start not in dates or end not in dates:
        raise ValueError("Selected market must have exact start_date and end_date bars.")
    signals = build_signals(bars, inputs)
    args = (bars, signals, start, end, inputs["initial_cash"], inputs["fee_rate"], inputs["slippage_rate"])
    strategy = simulate(*args)
    benchmark = simulate(*args, benchmark=True)
    strategy["metrics"] = measure(strategy)
    benchmark["metrics"] = measure(benchmark)
    ml = compare(bars, signals, start, end, inputs["enable_ml"])
    return dict(
        engine_version=ENGINE_VERSION,
        market_id=inputs["market_id"],
        start_date=start,
        end_date=end,
        strategy=strategy,
        benchmark=benchmark,
        excess_total_return=strategy["metrics"]["total_return"] - benchmark["metrics"]["total_return"],
        signals=[s for s in signals if start <= s["signal_date"] <= end],
        model_comparison=ml,
        libraries={k: version(k) for k in ["numpy", "TA-Lib", "scikit-learn"]},
        methodology=dict(
            execution="previous completed candle signal -> next opening fill",
            position="long or cash; fractional units; all available cash on entry",
            fee="percentage of executed notional on buys and sells",
            slippage="adverse fraction of opening price on each fill",
            unit_tick="0.000000000000000001",
            end_policy="mark remaining position at final close; no forced liquidation",
            benchmark="buy at first opening using same initial cash, fees and slippage; hold to final close",
            model_controls_trades=False,
        ),
        limitations=[
            "Simulation assumes full fills with no spread, liquidity, market-impact or minimum-order rules beyond configured slippage.",
            "A historical result is not a promise of future performance.",
            "No leverage, short selling, wallet connection, exchange orders, tax accounting or live trading.",
        ],
    )
