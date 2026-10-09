"""Owner-scoped workspace workflows and immutable backtest evidence."""

import csv
import io
import json
import hashlib
import math
from decimal import Decimal
from datetime import timedelta
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from .database import get_db
from .security import current_user
from .models import Workspace, Dataset, Backtest
from .schemas import WorkspaceInput, DatasetInput, CsvInput, BacktestInput, utc_today, ComparisonInput
from .services import mutation
from .imports import preview, normalize
from .engine import evaluate, ENGINE_VERSION

router = APIRouter(prefix="/api/v1")
Key = Header(min_length=1, max_length=100)


def owned_workspace(db, identifier, user):
    obj = db.scalar(select(Workspace).where(Workspace.id == identifier, Workspace.user_id == user.id))
    if not obj:
        raise HTTPException(404, "Workspace not found in your account.")
    return obj


def owned_backtest(db, identifier, user):
    obj = db.scalar(select(Backtest).join(Workspace).where(Backtest.id == identifier, Workspace.user_id == user.id))
    if not obj:
        raise HTTPException(404, "Backtest not found in your account.")
    return obj


def workspace_view(x):
    return dict(id=x.id, name=x.name, quote_currency=x.quote_currency)


def dataset_view(x):
    return dict(
        id=x.id,
        workspace_id=x.workspace_id,
        source=x.source,
        coverage_end=x.coverage_end,
        candles=x.candles,
        venue=x.venue,
        quote_currency="USD",
        quality=x.quality,
        created_at=x.created_at,
    )


def backtest_view(x):
    return dict(
        id=x.id,
        workspace_id=x.workspace_id,
        dataset_id=x.dataset_id,
        inputs=x.inputs,
        results=x.results,
        engine_version=x.engine_version,
        created_at=x.created_at,
    )


@router.get("/workspaces")
def workspaces(user=Depends(current_user), db=Depends(get_db)):
    return [workspace_view(x) for x in db.scalars(select(Workspace).where(Workspace.user_id == user.id))]


@router.post("/workspaces", status_code=201)
def create_workspace(data: WorkspaceInput, idempotency_key: str = Key, user=Depends(current_user), db=Depends(get_db)):
    def work():
        x = Workspace(user_id=user.id, **data.model_dump())
        db.add(x)
        db.flush()
        return workspace_view(x)

    return mutation(db, user, "workspace", idempotency_key, data.model_dump(mode="json"), work)


@router.post("/imports/preview")
def preview_import(data: CsvInput, user=Depends(current_user)):
    try:
        return preview(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/workspaces/{identifier}/datasets")
def datasets(identifier: str, user=Depends(current_user), db=Depends(get_db)):
    owned_workspace(db, identifier, user)
    return [
        dataset_view(x)
        for x in db.scalars(
            select(Dataset).where(Dataset.workspace_id == identifier).order_by(Dataset.created_at.desc())
        )
    ]


@router.post("/workspaces/{identifier}/datasets", status_code=201)
def create_dataset(
    identifier: str, data: DatasetInput, idempotency_key: str = Key, user=Depends(current_user), db=Depends(get_db)
):
    owned_workspace(db, identifier, user)
    try:
        candles, quality = normalize(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    fingerprint = hashlib.sha256(
        json.dumps(
            dict(candles=candles, venue=data.venue, source=data.source, coverage_end=str(data.coverage_end)),
            sort_keys=True,
        ).encode()
    ).hexdigest()

    def work():
        prior = db.scalar(select(Dataset).where(Dataset.workspace_id == identifier, Dataset.fingerprint == fingerprint))
        if prior:
            return dataset_view(prior)
        x = Dataset(
            workspace_id=identifier,
            source=data.source,
            coverage_end=str(data.coverage_end),
            candles=candles,
            venue=data.venue,
            quality=quality,
            fingerprint=fingerprint,
        )
        db.add(x)
        db.flush()
        return dataset_view(x)

    return mutation(db, user, "dataset:" + identifier, idempotency_key, data.model_dump(mode="json"), work)


@router.post("/workspaces/{identifier}/backtests", status_code=201)
def run_backtest(
    identifier: str, data: BacktestInput, idempotency_key: str = Key, user=Depends(current_user), db=Depends(get_db)
):
    p = owned_workspace(db, identifier, user)
    d = db.scalar(select(Dataset).where(Dataset.id == data.dataset_id, Dataset.workspace_id == identifier))
    if not d:
        raise HTTPException(404, "Dataset not found in this workspace.")
    inputs = dict(
        **data.model_dump(mode="json"),
        workspace=workspace_view(p),
        source=d.source,
        coverage_end=d.coverage_end,
        candles=d.candles,
        venue=d.venue,
        quality=d.quality,
    )

    def work():
        try:
            results = evaluate(inputs)
            json.dumps(results, allow_nan=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        x = Backtest(
            workspace_id=identifier, dataset_id=d.id, inputs=inputs, results=results, engine_version=ENGINE_VERSION
        )
        db.add(x)
        db.flush()
        return backtest_view(x)

    return mutation(db, user, "backtest:" + identifier, idempotency_key, data.model_dump(mode="json"), work)


@router.get("/backtests")
def backtests(user=Depends(current_user), db=Depends(get_db)):
    return [
        backtest_view(x)
        for x in db.scalars(
            select(Backtest)
            .join(Workspace)
            .where(Workspace.user_id == user.id)
            .order_by(Backtest.created_at.desc())
            .limit(100)
        )
    ]


@router.get("/backtests/{identifier}")
def get_backtest(identifier: str, user=Depends(current_user), db=Depends(get_db)):
    return backtest_view(owned_backtest(db, identifier, user))


@router.get("/backtests/{identifier}/report")
def report(identifier: str, format: str = "json", user=Depends(current_user), db=Depends(get_db)):
    x = owned_backtest(db, identifier, user)
    if format == "json":
        text, media = json.dumps(backtest_view(x), indent=2), "application/json"
    elif format in {"equity", "trades", "round_trips", "signals", "predictions"}:
        keys = {
            "equity": [
                "date",
                "cash",
                "quantity",
                "market_value",
                "equity",
                "cost_basis",
                "realized_pnl",
                "unrealized_pnl",
                "fees_paid",
                "slippage_cost",
                "target_at_open",
                "signal_date",
                "daily_return",
                "drawdown",
            ],
            "trades": [
                "date",
                "signal_date",
                "side",
                "quantity",
                "reference_open",
                "execution_price",
                "notional",
                "fee",
                "slippage_cost",
                "cash_after",
                "realized_pnl",
                "reason",
            ],
            "round_trips": ["entry_date", "exit_date", "quantity", "entry_cost", "exit_proceeds", "net_pnl"],
            "signals": ["signal_date", "target", "ready", "reason", "sma_fast", "sma_slow", "rsi"],
            "predictions": ["fold_id", "decision_date", "target_date", "actual", "ridge", "training_mean"],
        }[format]
        rows = (
            x.results["strategy"]["history"]
            if format == "equity"
            else x.results["strategy"][format]
            if format in {"trades", "round_trips"}
            else x.results["model_comparison"]["predictions"]
            if format == "predictions"
            else x.results["signals"]
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(keys)
        for row in rows:
            values = []
            for k in keys:
                v = row.get(k)
                if isinstance(v, dict):
                    v = json.dumps(v, sort_keys=True)
                if (
                    isinstance(v, str)
                    and k
                    in {
                        "date",
                        "signal_date",
                        "side",
                        "reason",
                        "entry_date",
                        "exit_date",
                        "decision_date",
                        "target_date",
                    }
                    and v.lstrip().startswith(("=", "+", "-", "@"))
                ):
                    v = "'" + v
                values.append(v)
            writer.writerow(values)
        text, media = output.getvalue(), "text/csv"
    else:
        raise HTTPException(422, "Use json, equity, trades, round_trips, signals or predictions format.")
    ext = "json" if format == "json" else "csv"
    return Response(
        text,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="strategy-{format}-{x.id}.{ext}"'},
    )


@router.post("/demo", status_code=201)
def demo(idempotency_key: str = Key, user=Depends(current_user), db=Depends(get_db)):
    def work():
        if db.scalar(select(Workspace).where(Workspace.user_id == user.id)):
            raise HTTPException(409, "Demo requires an empty workspace catalog.")
        p = Workspace(user_id=user.id, name="Synthetic Strategy Lab", quote_currency="USD")
        db.add(p)
        db.flush()
        end = utc_today() - timedelta(days=1)
        start = end - timedelta(days=179)
        candles = []
        for market, base in [("bitcoin-usd", 50000), ("ethereum-usd", 2500)]:
            previous = base
            for i in range(180):
                close = base * (1 + 0.001 * i + 0.055 * math.sin(i * 0.22)) * (0.82 if i >= 155 else 1)
                opening = previous
                candles.append(
                    dict(
                        date=str(start + timedelta(days=i)),
                        market_id=market,
                        open=f"{opening:.8f}",
                        high=f"{max(opening, close) * 1.02:.8f}",
                        low=f"{min(opening, close) * 0.98:.8f}",
                        close=f"{close:.8f}",
                        volume=f"{(1200 + 200 * math.sin(i * 0.4)) * (4 if i == 155 else 1):.8f}",
                    )
                )
                previous = close
        data = DatasetInput(source="Synthetic offline demonstration", venue="demo", coverage_end=end, candles=candles)
        rows, quality = normalize(data)
        d = Dataset(
            workspace_id=p.id,
            source=data.source,
            venue=data.venue,
            coverage_end=str(end),
            candles=rows,
            quality=quality,
            fingerprint=hashlib.sha256(
                json.dumps(
                    dict(candles=rows, venue=data.venue, source=data.source, coverage_end=str(end)), sort_keys=True
                ).encode()
            ).hexdigest(),
        )
        db.add(d)
        db.flush()
        return dict(
            workspace_id=p.id,
            dataset_id=d.id,
            start_date=str(start + timedelta(days=50)),
            end_date=str(end),
            market_id="bitcoin-usd",
            message="Synthetic candles; no live feed connected.",
        )

    return mutation(db, user, "demo", idempotency_key, {}, work)


@router.post("/comparisons")
def comparison(data: ComparisonInput, user=Depends(current_user), db=Depends(get_db)):
    records = [owned_backtest(db, k, user) for k in data.backtest_ids]
    fields = ["dataset_id", "market_id", "start_date", "end_date", "initial_cash"]
    first = records[0]
    if any(
        any(
            (
                Decimal(x.inputs[k]) != Decimal(first.inputs[k])
                if k == "initial_cash"
                else x.inputs[k] != first.inputs[k]
            )
            for k in fields
        )
        for x in records[1:]
    ):
        raise HTTPException(422, "Compare the same dataset, market, date range and initial cash.")
    rows = []
    for x in records:
        r = x.results["strategy"]
        m = r["metrics"]
        rows.append(
            dict(
                backtest_id=x.id,
                name=x.inputs["name"],
                strategy=x.inputs["strategy"],
                fee_rate=x.inputs["fee_rate"],
                slippage_rate=x.inputs["slippage_rate"],
                final_equity=r["final_equity"],
                total_return=m["total_return"],
                max_drawdown=m["max_drawdown"],
                sharpe_zero_risk_free=m["sharpe_zero_risk_free"],
                trade_count=m["trade_count"],
                fees_paid=r["fees_paid"],
                benchmark_return=x.results["benchmark"]["metrics"]["total_return"],
                excess_total_return=x.results["excess_total_return"],
            )
        )
    return dict(
        common_inputs={k: first.inputs[k] for k in fields},
        varying_cost_assumptions=len(
            {(Decimal(x.inputs["fee_rate"]), Decimal(x.inputs["slippage_rate"])) for x in records}
        )
        > 1,
        rows=rows,
        interpretation="Saved historical experiments; compare visible cost assumptions and do not interpret the largest historical return as future performance.",
    )
