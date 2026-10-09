"""Preview before commit; reject gaps rather than inventing candles."""

import csv
import io
from collections import defaultdict
from datetime import date
from pydantic import ValidationError
from .schemas import DatasetInput

COLUMNS = ["date", "market_id", "open", "high", "low", "close", "volume"]


def normalize(data):
    rows = sorted([x.model_dump(mode="json") for x in data.candles], key=lambda x: (x["market_id"], x["date"]))
    groups = defaultdict(list)
    for row in rows:
        if row["date"] > str(data.coverage_end):
            raise ValueError("A candle is later than coverage_end.")
        groups[row["market_id"]].append(row)
    if len(groups) > 20:
        raise ValueError("A dataset can contain at most 20 markets.")
    for market, bars in groups.items():
        if len(bars) > 730:
            raise ValueError("Use at most 730 daily candles per market.")
        days = [date.fromisoformat(x["date"]) for x in bars]
        for a, b in zip(days, days[1:]):
            if (b - a).days != 1:
                raise ValueError(f"{market}: duplicate or missing daily candle after {a}.")
    return rows, dict(
        row_count=len(rows),
        market_count=len(groups),
        markets={k: dict(count=len(v), first_date=v[0]["date"], last_date=v[-1]["date"]) for k, v in groups.items()},
        volume_unit="base asset units",
        timeframe="1d",
        timezone="UTC",
        warnings=["Source and venue are user-declared; the API does not verify provider accuracy."],
    )


def preview(data):
    try:
        reader = csv.DictReader(io.StringIO(data.candles_csv))
        if reader.fieldnames != COLUMNS:
            raise ValueError("Use this exact CSV header: " + ",".join(COLUMNS))
        rows = []
        for line, row in enumerate(reader, start=2):
            if line > 15001 or None in row or any(v is None for v in row.values()):
                raise ValueError(f"Malformed or excessive CSV data at line {line}.")
            rows.append(row)
        dataset = DatasetInput(**data.model_dump(exclude={"candles_csv"}), candles=rows)
        normalized, quality = normalize(dataset)
        return dict(
            dataset={**dataset.model_dump(mode="json", exclude={"candles"}), "candles": normalized}, quality=quality
        )
    except ValidationError as exc:
        # Field locations and messages only; do not echo the original upload.
        raise ValueError("; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors()[:5])) from None
