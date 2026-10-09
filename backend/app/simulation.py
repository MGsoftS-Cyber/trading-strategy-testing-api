"""Fractional long/cash simulation using decimal accounting and next-open fills."""

from decimal import Decimal, localcontext, ROUND_DOWN

UNIT_TICK = Decimal("1e-18")


def text(value):
    return format(value, "f")


def simulate(bars, signals, start_date, end_date, initial_cash, fee_rate, slippage_rate, benchmark=False):
    with localcontext() as context:
        context.prec = 60
        return _run(
            bars,
            signals,
            start_date,
            end_date,
            Decimal(initial_cash),
            Decimal(fee_rate),
            Decimal(slippage_rate),
            benchmark,
        )


def _run(bars, signals, start, end, cash, fee, slippage, benchmark):
    initial = cash
    units = Decimal(0)
    basis = Decimal(0)
    entry = None
    fees = Decimal(0)
    slippage_cost = Decimal(0)
    realized = Decimal(0)
    history = []
    trades = []
    round_trips = []
    skipped_orders = []
    selected = [i for i, row in enumerate(bars) if start <= row["date"] <= end]
    for i in selected:
        bar = bars[i]
        opening = Decimal(bar["open"])
        close = Decimal(bar["close"])
        prior = signals[i - 1] if i > 0 else None
        target = 1 if benchmark else prior["target"] if prior else 0
        reason = "buy_hold_entry" if benchmark else prior["reason"] if prior else "no_previous_bar"
        signal_date = None if benchmark else prior["signal_date"] if prior else None
        if target == 1 and units == 0:
            execution = opening * (1 + slippage)
            bought = (cash / (execution * (1 + fee))).quantize(UNIT_TICK, rounding=ROUND_DOWN)
            if bought > 0:
                notional = bought * execution
                cost = notional * fee
                basis = notional + cost
                cash -= basis
                units = bought
                fees += cost
                impact = bought * (execution - opening)
                slippage_cost += impact
                entry = dict(date=bar["date"], quantity=text(units), entry_cost=text(basis))
                trades.append(
                    dict(
                        date=bar["date"],
                        signal_date=signal_date,
                        side="buy",
                        quantity=text(bought),
                        reference_open=text(opening),
                        execution_price=text(execution),
                        notional=text(notional),
                        fee=text(cost),
                        slippage_cost=text(impact),
                        cash_after=text(cash),
                        realized_pnl="0",
                        reason=reason,
                    )
                )
            else:
                skipped_orders.append(
                    dict(date=bar["date"], reason="cash_below_one_quantity_tick", signal_date=signal_date)
                )
        elif target == 0 and units > 0:
            execution = opening * (1 - slippage)
            notional = units * execution
            cost = notional * fee
            proceeds = notional - cost
            pnl = proceeds - basis
            cash += proceeds
            fees += cost
            realized += pnl
            impact = units * (opening - execution)
            slippage_cost += impact
            trades.append(
                dict(
                    date=bar["date"],
                    signal_date=signal_date,
                    side="sell",
                    quantity=text(units),
                    reference_open=text(opening),
                    execution_price=text(execution),
                    notional=text(notional),
                    fee=text(cost),
                    slippage_cost=text(impact),
                    cash_after=text(cash),
                    realized_pnl=text(pnl),
                    reason=reason,
                )
            )
            round_trips.append(
                dict(
                    entry_date=entry["date"],
                    exit_date=bar["date"],
                    quantity=text(units),
                    entry_cost=entry["entry_cost"],
                    exit_proceeds=text(proceeds),
                    net_pnl=text(pnl),
                )
            )
            units = Decimal(0)
            basis = Decimal(0)
            entry = None
        value = units * close
        equity = cash + value
        # This identity includes entry fees in cost basis and exit fees in realized P/L.
        unrealized = value - basis
        assert cash >= 0 and units >= 0
        history.append(
            dict(
                date=bar["date"],
                close=text(close),
                cash=text(cash),
                quantity=text(units),
                market_value=text(value),
                equity=text(equity),
                cost_basis=text(basis),
                realized_pnl=text(realized),
                unrealized_pnl=text(unrealized),
                fees_paid=text(fees),
                slippage_cost=text(slippage_cost),
                target_at_open=target,
                signal_date=signal_date,
            )
        )
    return dict(
        history=history,
        trades=trades,
        round_trips=round_trips,
        skipped_orders=skipped_orders,
        initial_cash=text(initial),
        fees_paid=text(fees),
        slippage_cost=text(slippage_cost),
        open_position=entry,
        final_equity=history[-1]["equity"],
        final_cash=history[-1]["cash"],
        final_quantity=history[-1]["quantity"],
        realized_pnl=text(realized),
        unrealized_pnl=history[-1]["unrealized_pnl"],
    )
