"""Real HTTP exercise: import, two strategy runs, comparison and every export."""

import argparse
import csv
import json
import secrets
from pathlib import Path
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8010")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
with httpx.Client(base_url=args.url, trust_env=False, timeout=60) as client:
    assert client.get("/api/health").status_code == 200
    r = client.post(
        "/api/auth/register",
        json={"email": f"demo-{secrets.token_hex(6)}@example.test", "password": secrets.token_urlsafe(24)},
    )
    r.raise_for_status()
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    client.headers["Idempotency-Key"] = secrets.token_hex(12)
    d = client.post("/api/v1/demo")
    d.raise_for_status()
    demo = d.json()
    path = f"/api/v1/workspaces/{demo['workspace_id']}"
    dataset = client.get(path + "/datasets").json()[0]
    with (root / "examples/candles.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "market_id", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(dataset["candles"])
    preview = client.post(
        "/api/v1/imports/preview",
        json=dict(
            candles_csv=(root / "examples/candles.csv").read_text(),
            source=dataset["source"],
            venue=dataset["venue"],
            coverage_end=dataset["coverage_end"],
        ),
    )
    preview.raise_for_status()
    client.headers["Idempotency-Key"] = secrets.token_hex(12)
    imported = client.post(path + "/datasets", json=preview.json()["dataset"])
    imported.raise_for_status()
    assert imported.json()["id"] == dataset["id"]
    reports = []
    for strategy in ["sma_cross", "rsi_reversion"]:
        client.headers["Idempotency-Key"] = secrets.token_hex(12)
        payload = dict(
            dataset_id=dataset["id"],
            market_id=demo["market_id"],
            start_date=demo["start_date"],
            end_date=demo["end_date"],
            strategy=strategy,
            name=strategy + " synthetic experiment",
        )
        r = client.post(path + "/backtests", json=payload)
        r.raise_for_status()
        result = r.json()
        reports.append(result)
        assert len(result["results"]["strategy"]["history"]) == 130
        assert result["results"]["model_comparison"]["status"] == "available"
        (root / f"examples/{strategy}-report.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        for fmt in ["json", "equity", "trades", "round_trips", "signals", "predictions"]:
            exported = client.get(f"/api/v1/backtests/{result['id']}/report", params={"format": fmt})
            exported.raise_for_status()
            if fmt != "json":
                (root / f"examples/{strategy}-{fmt}.csv").write_text(exported.text)
    comparison = client.post("/api/v1/comparisons", json={"backtest_ids": [r["id"] for r in reports]})
    comparison.raise_for_status()
    (root / "examples/comparison.json").write_text(json.dumps(comparison.json(), indent=2))
    schema = client.get("/openapi.json")
    schema.raise_for_status()
    (root / "docs/openapi.json").write_text(json.dumps(schema.json(), indent=2))
    assert client.get("/docs").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/session").status_code == 401
    print(
        "HTTP smoke passed: auth, demo, CSV preview/import, two strategies, comparison, all six exports, Swagger and logout."
    )
    for r in reports:
        s = r["results"]["strategy"]
        print(
            r["inputs"]["strategy"],
            ":",
            len(s["history"]),
            "days;",
            len(s["trades"]),
            "fills;",
            len(r["results"]["model_comparison"]["predictions"]),
            "temporal test predictions.",
        )
