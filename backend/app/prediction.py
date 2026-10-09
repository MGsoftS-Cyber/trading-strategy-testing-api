"""Expanding-window Ridge versus training-mean baseline; predictions do not trade."""

import math
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.dummy import DummyRegressor
from threadpoolctl import threadpool_limits

PARAMETERS = dict(
    min_train_rows=60,
    min_test_rows=20,
    refit_every=20,
    ridge_alpha=1.0,
    features=["daily_return", "sma_fast/sma_slow - 1", "rsi/100", "volatility20"],
    target="next completed candle close/open - 1",
)


def compare(bars, signals, start, end, enabled):
    if not enabled:
        return dict(status="disabled", parameters=PARAMETERS, folds=[], predictions=[])
    close = np.array([float(x["close"]) for x in bars])
    returns = np.full(len(close), np.nan)
    returns[1:] = close[1:] / close[:-1] - 1
    rows = []
    for i in range(20, len(bars) - 1):
        s = signals[i]
        if s["sma_fast"] is None or s["sma_slow"] is None or s["rsi"] is None:
            continue
        x = [
            float(returns[i]),
            s["sma_fast"] / s["sma_slow"] - 1,
            s["rsi"] / 100,
            float(np.std(returns[i - 19 : i + 1], ddof=1)),
        ]
        actual = float(bars[i + 1]["close"]) / float(bars[i + 1]["open"]) - 1
        rows.append(dict(decision_date=bars[i]["date"], target_date=bars[i + 1]["date"], features=x, actual=actual))
    eligible = [i for i, r in enumerate(rows) if i >= 60 and start <= r["target_date"] <= end]
    if len(eligible) < 20:
        return dict(
            status="insufficient_history",
            reason="Need 60 earlier labeled feature rows plus at least 20 later scoring rows inside the requested range.",
            parameters=PARAMETERS,
            folds=[],
            predictions=[],
        )
    arr = np.array([r["features"] + [r["actual"]] for r in rows])
    if not np.isfinite(arr).all() or np.max(np.abs(arr)) > 1e6:
        return dict(status="unsupported_numeric_range", parameters=PARAMETERS, folds=[], predictions=[])
    folds = []
    predictions = []
    for offset in range(0, len(eligible), 20):
        chunk = eligible[offset : offset + 20]
        first = chunk[0]
        train = rows[:first]
        x = np.array([r["features"] for r in train])
        y = np.array([r["actual"] for r in train])
        test = np.array([rows[i]["features"] for i in chunk])
        assert train[-1]["target_date"] <= rows[first]["decision_date"]
        with threadpool_limits(limits=1):
            ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0, solver="svd")).fit(x, y)
            dummy = DummyRegressor(strategy="mean").fit(x, y)
            rp = ridge.predict(test)
            dp = dummy.predict(test)
        fold_id = len(folds) + 1
        folds.append(
            dict(
                fold_id=fold_id,
                training_rows=len(train),
                train_decision_start=train[0]["decision_date"],
                train_decision_end=train[-1]["decision_date"],
                train_target_end=train[-1]["target_date"],
                first_test_decision=rows[first]["decision_date"],
                last_test_decision=rows[chunk[-1]]["decision_date"],
                test_rows=len(chunk),
            )
        )
        for i, r, d in zip(chunk, rp, dp):
            predictions.append(
                dict(
                    fold_id=fold_id,
                    decision_date=rows[i]["decision_date"],
                    target_date=rows[i]["target_date"],
                    actual=rows[i]["actual"],
                    ridge=float(r),
                    training_mean=float(d),
                )
            )
    actual = np.array([r["actual"] for r in predictions])
    scores = {}
    for name in ["ridge", "training_mean"]:
        pred = np.array([r[name] for r in predictions])
        err = pred - actual
        scores[name] = dict(
            mae=float(np.mean(np.abs(err))),
            rmse=float(math.sqrt(np.mean(err**2))),
            direction_accuracy=float(np.mean((pred > 0) == (actual > 0))),
            rows=len(actual),
        )
    return dict(
        status="available",
        parameters=PARAMETERS,
        folds=folds,
        predictions=predictions,
        scores=scores,
        interpretation="Temporal out-of-sample predictions for historical evaluation only; no model controls the simulated strategy and no profitability claim.",
    )
