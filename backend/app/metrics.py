"""End-of-day equity statistics include first-day entry costs against initial cash."""

import math
import numpy as np


def measure(run):
    history = run["history"]
    initial = float(run["initial_cash"])
    equity = np.array([initial] + [float(x["equity"]) for x in history], dtype="float64")
    returns = equity[1:] / equity[:-1] - 1
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1
    total = float(equity[-1] / initial - 1)
    n = len(history)
    exponent = math.log(equity[-1] / initial) * 365 / n
    cagr = math.expm1(exponent) if exponent < 700 else None
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    vol = std * math.sqrt(365)
    sharpe = float(np.mean(returns) / std * math.sqrt(365)) if std > 1e-15 else None
    pnl = [float(x["net_pnl"]) for x in run["round_trips"]]
    gains = sum(x for x in pnl if x > 0)
    losses = -sum(x for x in pnl if x < 0)
    for row, r, dd in zip(history, returns, drawdowns[1:]):
        row["daily_return"] = float(r)
        row["drawdown"] = float(dd)
    return dict(
        total_return=total,
        cagr=cagr,
        cagr_reason="numeric_range" if cagr is None else None,
        max_drawdown=float(-min(drawdowns)),
        annualized_volatility=vol,
        sharpe_zero_risk_free=sharpe,
        days=n,
        exposure_fraction=sum(float(x["quantity"]) > 0 for x in history) / n,
        trade_count=len(run["trades"]),
        closed_round_trips=len(pnl),
        win_rate=sum(x > 0 for x in pnl) / len(pnl) if pnl else None,
        profit_factor=gains / losses if losses > 0 else None,
        profit_factor_reason="no_closed_losses" if losses == 0 else None,
        return_basis="end-of-day marks with initial cash as first opening baseline; 365-day annualization",
        warnings=[
            "Short-window annualized values can be misleading.",
            "Drawdown samples closes, not intraday lows.",
            "Open positions are marked at last close; hypothetical future exit fees are not charged.",
        ],
    )
