"""Closed-bar target states, never same-close fills."""

import numpy as np
import talib


def build_signals(bars, inputs):
    close = np.array([float(x["close"]) for x in bars], dtype="float64")
    fast = talib.SMA(close, inputs["fast_period"])
    slow = talib.SMA(close, inputs["slow_period"])
    rsi = talib.RSI(close, inputs["rsi_period"])
    states = []
    target = 0
    for i, row in enumerate(bars):
        ready = False
        reason = "indicator_warmup"
        if inputs["strategy"] == "sma_cross":
            if np.isfinite(fast[i]) and np.isfinite(slow[i]):
                ready = True
                reason = (
                    "fast_above_slow"
                    if fast[i] > slow[i]
                    else "fast_below_slow"
                    if fast[i] < slow[i]
                    else "equal_means_hold"
                )
                if fast[i] > slow[i]:
                    target = 1
                elif fast[i] < slow[i]:
                    target = 0
        else:
            if np.isfinite(rsi[i]):
                ready = True
                reason = "rsi_middle_hold"
                if rsi[i] <= inputs["rsi_low"]:
                    target = 1
                    reason = "rsi_low_long"
                elif rsi[i] >= inputs["rsi_high"]:
                    target = 0
                    reason = "rsi_high_cash"
        states.append(
            dict(
                signal_date=row["date"],
                target=target,
                ready=ready,
                reason=reason,
                sma_fast=float(fast[i]) if np.isfinite(fast[i]) else None,
                sma_slow=float(slow[i]) if np.isfinite(slow[i]) else None,
                rsi=float(rsi[i]) if np.isfinite(rsi[i]) else None,
            )
        )
    return states
