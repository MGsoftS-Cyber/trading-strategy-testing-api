from datetime import date, timedelta
from decimal import Decimal, localcontext, ROUND_DOWN
import math
import json
import copy
import numpy as np
import pytest
from pydantic import ValidationError
from app.schemas import BacktestInput, DatasetInput, CandleInput, utc_today
from app.imports import normalize
from app.signals import build_signals
from app.simulation import simulate, UNIT_TICK
from app.metrics import measure
from app.prediction import compare
from app.engine import evaluate


def bars(n=180, kind="wave"):
    start = date(2025, 1, 1)
    out = []
    for i in range(n):
        price = 100 + 0.2 * i + 10 * math.sin(i * 0.22) if kind == "wave" else 100 + i if kind == "up" else 100
        opening = price * (1 + 0.01 * math.sin(i * 0.4))
        out.append(
            dict(
                date=str(start + timedelta(days=i)),
                market_id="bitcoin-usd",
                open=f"{opening:.8f}",
                high=f"{max(opening, price) + 2:.8f}",
                low=f"{min(opening, price) - 2:.8f}",
                close=f"{price:.8f}",
                volume="100",
            )
        )
    return out


def inputs(b=None, **updates):
    b = b or bars()
    p = dict(
        dataset_id="demo",
        market_id="bitcoin-usd",
        start_date=b[50]["date"] if len(b) > 50 else b[0]["date"],
        end_date=b[-1]["date"],
        strategy="sma_cross",
        initial_cash="1000",
        fee_rate="0.001",
        slippage_rate="0.001",
        fast_period=10,
        slow_period=30,
        rsi_period=14,
        rsi_low=30,
        rsi_high=70,
        enable_ml=True,
    )
    p.update(updates)
    p.update(candles=b, coverage_end=b[-1]["date"])
    return p


def manual_signals(b, targets):
    return [dict(signal_date=r["date"], target=t, ready=True, reason="manual") for r, t in zip(b, targets)]


def test_next_open_fill_and_last_signal_does_not_fill():
    b = bars(3, kind="flat")
    b[1]["open"] = "200"
    result = simulate(b, manual_signals(b, [1, 0, 1]), b[0]["date"], b[-1]["date"], "1000", "0", "0")
    assert [r["date"] for r in result["trades"]] == [b[1]["date"], b[2]["date"]]
    assert result["trades"][0]["signal_date"] == b[0]["date"]
    assert result["trades"][0]["execution_price"] == "200"
    assert Decimal(result["trades"][0]["quantity"]) == 5
    assert len(result["round_trips"]) == 1


def test_fee_slippage_roundtrip_and_cash_identity():
    b = bars(3, kind="flat")
    b[1]["open"] = "100"
    b[2]["open"] = "110"
    result = simulate(b, manual_signals(b, [1, 0, 0]), b[0]["date"], b[-1]["date"], "1000", "0.01", "0.02")
    with localcontext() as ctx:
        ctx.prec = 60
        quantity = (Decimal(1000) / (Decimal(102) * Decimal("1.01"))).quantize(UNIT_TICK, rounding=ROUND_DOWN)
        basis = quantity * Decimal(102) * Decimal("1.01")
        proceeds = quantity * Decimal("107.8") * Decimal("0.99")
        assert Decimal(result["trades"][0]["quantity"]) == quantity
        assert Decimal(result["realized_pnl"]) == proceeds - basis
        assert Decimal(result["fees_paid"]) == quantity * Decimal(102) * Decimal(".01") + quantity * Decimal(
            "107.8"
        ) * Decimal(".01")
    assert Decimal(result["final_quantity"]) == 0
    assert Decimal(result["final_equity"]) == Decimal(result["final_cash"])
    assert len(result["round_trips"]) == 1


def test_no_repeat_buy_while_already_long():
    b = bars(5)
    r = simulate(b, manual_signals(b, [1] * 5), b[0]["date"], b[-1]["date"], "1000", "0", "0")
    assert len(r["trades"]) == 1
    assert r["open_position"] is not None
    assert r["round_trips"] == []


def test_no_forced_final_liquidation():
    result = evaluate(inputs())["strategy"]
    assert result["open_position"] is not None
    assert Decimal(result["final_quantity"]) > 0
    assert result["trades"][-1]["side"] == "buy"


def test_pnl_identity_and_nonnegative_balances():
    r = evaluate(inputs())["strategy"]
    with localcontext() as ctx:
        ctx.prec = 60
        for h in r["history"]:
            assert Decimal(h["cash"]) >= 0
            assert Decimal(h["quantity"]) >= 0
            left = Decimal(h["equity"]) - 1000
            right = Decimal(h["realized_pnl"]) + Decimal(h["unrealized_pnl"])
            assert abs(left - right) < Decimal("1e-50")


def test_benchmark_first_open_and_matching_costs():
    r = evaluate(inputs())
    benchmark = r["benchmark"]
    assert len(benchmark["trades"]) == 1
    assert benchmark["trades"][0]["date"] == r["start_date"]
    assert benchmark["trades"][0]["signal_date"] is None
    assert r["excess_total_return"] == pytest.approx(
        r["strategy"]["metrics"]["total_return"] - benchmark["metrics"]["total_return"]
    )


def test_first_day_fees_appear_in_return_and_drawdown():
    b = bars(5, kind="flat")
    for row in b:
        row["open"] = "100"
    r = simulate(b, manual_signals(b, [0] * 5), b[0]["date"], b[-1]["date"], "1000", "0.01", "0", benchmark=True)
    m = measure(r)
    assert m["total_return"] == pytest.approx(1 / 1.01 - 1)
    assert m["max_drawdown"] == pytest.approx(1 - 1 / 1.01)
    assert r["history"][0]["daily_return"] == pytest.approx(1 / 1.01 - 1)


def test_zero_activity_metrics_are_defined():
    b = bars(5)
    r = simulate(b, manual_signals(b, [0] * 5), b[0]["date"], b[-1]["date"], "1000", "0", "0")
    m = measure(r)
    assert m["total_return"] == 0 and m["max_drawdown"] == 0
    assert m["sharpe_zero_risk_free"] is None
    assert m["win_rate"] is None and m["profit_factor"] is None
    assert m["exposure_fraction"] == 0


def test_volatility_uses_sample_returns_and_365():
    b = bars(5)
    r = simulate(b, manual_signals(b, [0] * 5), b[0]["date"], b[-1]["date"], "1000", "0", "0", benchmark=True)
    m = measure(r)
    arr = np.array([float(x["daily_return"]) for x in r["history"]])
    assert m["annualized_volatility"] == pytest.approx(np.std(arr, ddof=1) * math.sqrt(365))


def test_signal_warmup_and_positive_ma_state():
    b = bars(kind="up")
    s = build_signals(b, inputs(b))
    assert not s[28]["ready"] and s[28]["target"] == 0
    assert s[29]["ready"] and s[29]["target"] == 1
    assert s[29]["sma_fast"] > s[29]["sma_slow"]


def test_rsi_entries_hold_and_exit():
    b = bars()
    p = inputs(b, strategy="rsi_reversion", rsi_low=40, rsi_high=60)
    s = build_signals(b, p)
    assert not s[13]["ready"]
    assert any(r["reason"] == "rsi_low_long" for r in s)
    assert any(r["reason"] == "rsi_high_cash" for r in s)
    for i, r in enumerate(s):
        if i and r["reason"] == "rsi_middle_hold":
            assert r["target"] == s[i - 1]["target"]


def test_future_prefix_invariance_in_simulation():
    b = bars()
    cut = b[139]["date"]
    longer = evaluate(inputs(b, end_date=cut))
    shorter = evaluate(inputs(b[:140]))
    assert longer["strategy"] == shorter["strategy"]
    assert longer["model_comparison"] == shorter["model_comparison"]


def test_walkforward_targets_known_at_fit_and_prefix_predictions():
    b = bars()
    s = build_signals(b, inputs(b))
    m = compare(b, s, b[50]["date"], b[-1]["date"], True)
    assert m["status"] == "available"
    for fold in m["folds"]:
        assert fold["train_target_end"] <= fold["first_test_decision"]
        assert fold["train_decision_end"] < fold["first_test_decision"]
        assert fold["training_rows"] >= 60 and fold["test_rows"] <= 20
    short = compare(b[:140], s[:140], b[50]["date"], b[139]["date"], True)
    assert short["predictions"] == m["predictions"][: len(short["predictions"])]
    assert m["scores"]["ridge"]["rows"] == len(m["predictions"])


def test_mutating_future_candles_does_not_change_prior_predictions():
    b = bars()
    other = copy.deepcopy(b)
    for row in other[150:]:
        row["close"] = str(float(row["close"]) * 2)
    a = compare(b, build_signals(b, inputs(b)), b[50]["date"], b[-1]["date"], True)
    c = compare(other, build_signals(other, inputs(other)), b[50]["date"], b[-1]["date"], True)
    assert [p for p in a["predictions"] if p["target_date"] < b[150]["date"]] == [
        p for p in c["predictions"] if p["target_date"] < b[150]["date"]
    ]


def test_model_disabled_and_short_range():
    b = bars()
    s = build_signals(b, inputs(b))
    assert compare(b, s, b[50]["date"], b[-1]["date"], False)["status"] == "disabled"
    assert compare(b, s, b[170]["date"], b[-1]["date"], True)["status"] == "insufficient_history"


def test_model_flat_data_has_finite_zero_errors():
    b = bars(kind="flat")
    for row in b:
        row["open"] = row["close"]
    m = compare(b, build_signals(b, inputs(b)), b[50]["date"], b[-1]["date"], True)
    assert m["status"] == "available"
    assert m["scores"]["ridge"]["mae"] == 0
    json.dumps(m, allow_nan=False)


@pytest.mark.parametrize(
    "update", [{"market_id": "absent-usd"}, {"start_date": "2024-12-31"}, {"end_date": "2025-12-31"}]
)
def test_invalid_selection(update):
    with pytest.raises(ValueError):
        evaluate(inputs(**update))


@pytest.mark.parametrize(
    "update",
    [
        {"initial_cash": 1000},
        {"fee_rate": "0.1"},
        {"slippage_rate": "-1"},
        {"fast_period": 30, "slow_period": 20},
        {"rsi_low": 80, "rsi_high": 70},
        {"end_date": "2025-01-01"},
    ],
)
def test_backtest_contract(update):
    data = inputs()
    data.pop("candles")
    data.pop("coverage_end")
    data.update(update)
    with pytest.raises(ValidationError):
        BacktestInput(**data)


@pytest.mark.parametrize(
    "change",
    [{"close": 100}, {"low": "0"}, {"high": "50"}, {"volume": "-1"}, {"close": "NaN"}, {"date": str(utc_today())}],
)
def test_candle_contract(change):
    row = bars(1)[0]
    row.update(change)
    with pytest.raises(ValidationError):
        CandleInput(**row)


@pytest.mark.parametrize("kind", ["duplicate", "gap", "after_coverage"])
def test_bad_dataset(kind):
    b = bars(5)
    if kind == "duplicate":
        b.append(copy.deepcopy(b[-1]))
    if kind == "gap":
        b.pop(2)
    end = b[-1]["date"] if kind != "after_coverage" else b[-2]["date"]
    with pytest.raises(ValueError):
        normalize(DatasetInput(source="test", venue="test", coverage_end=end, candles=b))


def test_quantity_tick_never_invents_affordable_units():
    b = bars(3)
    for row in b:
        row["open"] = "1000000000000000"
        row["close"] = row["open"]
    r = simulate(b, manual_signals(b, [1] * 3), b[0]["date"], b[-1]["date"], "0.000000000001", "0", "0")
    assert r["trades"] == []
    assert len(r["skipped_orders"]) == 2
    assert Decimal(r["final_cash"]) == Decimal("0.000000000001")


def test_win_rate_profit_factor_use_only_closed_net_roundtrips():
    b = bars(5)
    r = simulate(b, manual_signals(b, [0] * 5), b[0]["date"], b[-1]["date"], "1000", "0", "0")
    r["round_trips"] = [dict(net_pnl="2"), dict(net_pnl="-1"), dict(net_pnl="0")]
    m = measure(r)
    assert m["win_rate"] == pytest.approx(1 / 3)
    assert m["profit_factor"] == 2


def test_prediction_scores_match_exported_out_of_sample_rows():
    b = bars()
    m = compare(b, build_signals(b, inputs(b)), b[50]["date"], b[-1]["date"], True)
    for name in ["ridge", "training_mean"]:
        errors = [r[name] - r["actual"] for r in m["predictions"]]
        assert m["scores"][name]["mae"] == pytest.approx(sum(abs(x) for x in errors) / len(errors))
        assert m["scores"][name]["rmse"] == pytest.approx(math.sqrt(sum(x * x for x in errors) / len(errors)))
