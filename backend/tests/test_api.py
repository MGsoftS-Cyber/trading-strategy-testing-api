import json
import secrets
from app.security import _attempts


def signup(client, email="engineer@example.test"):
    r = client.post("/api/auth/register", json={"email": email, "password": "local-demo-password-123"})
    assert r.status_code == 201, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"], "Idempotency-Key": secrets.token_hex(12)}


def demo(client):
    headers = signup(client)
    d = client.post("/api/v1/demo", headers=headers)
    assert d.status_code == 201, d.text
    headers["Idempotency-Key"] = secrets.token_hex(12)
    data = d.json()
    a = client.post(
        f"/api/v1/workspaces/{data['workspace_id']}/backtests",
        headers=headers,
        json={
            "dataset_id": data["dataset_id"],
            "market_id": data["market_id"],
            "start_date": data["start_date"],
            "end_date": data["end_date"],
        },
    )
    assert a.status_code == 201, a.text
    return headers, data, a.json()


def test_complete_workflow_and_reports(client):
    headers, d, a = demo(client)
    assert a["results"]["model_comparison"]["status"] == "available"
    assert len(a["results"]["strategy"]["history"]) == 130
    assert a["results"]["strategy"]["metrics"]["trade_count"] > 0
    for fmt in ["json", "equity", "trades", "round_trips", "signals", "predictions"]:
        r = client.get(f"/api/v1/backtests/{a['id']}/report?format={fmt}")
        assert r.status_code == 200
        assert "attachment" in r.headers["content-disposition"]
    assert client.get("/api/v1/backtests").json()[0]["id"] == a["id"]
    assert client.get("/api/v1/backtests/" + a["id"]).json()["results"] == a["results"]
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_write_needs_csrf_and_auth(client):
    assert client.get("/api/v1/workspaces").status_code == 401
    signup(client)
    assert (
        client.post("/api/v1/workspaces", headers={"Idempotency-Key": "a"}, json={"name": "Watch"}).status_code == 403
    )


def test_untrusted_origin(client):
    h = signup(client)
    h["Origin"] = "https://evil.example"
    assert client.post("/api/v1/workspaces", headers=h, json={"name": "Watch"}).status_code == 403


def test_idempotency_and_conflict(client):
    h = signup(client)
    path = "/api/v1/workspaces"
    first = client.post(path, headers=h, json={"name": "Watch"})
    second = client.post(path, headers=h, json={"name": "Watch"})
    assert first.json() == second.json()
    assert client.post(path, headers=h, json={"name": "Other"}).status_code == 409
    assert len(client.get(path).json()) == 1


def test_backtest_replay_keeps_snapshot(client):
    h, d, a = demo(client)
    replay = client.post(
        f"/api/v1/workspaces/{d['workspace_id']}/backtests",
        headers=h,
        json={
            "dataset_id": d["dataset_id"],
            "market_id": d["market_id"],
            "start_date": d["start_date"],
            "end_date": d["end_date"],
        },
    )
    assert replay.json() == a
    assert len(client.get("/api/v1/backtests").json()) == 1


def test_owner_isolation(client):
    h, d, a = demo(client)
    client.cookies.clear()
    signup(client, "other@example.test")
    assert client.get("/api/v1/workspaces").json() == []
    assert client.get("/api/v1/backtests").json() == []
    assert client.get("/api/v1/backtests/" + a["id"]).status_code == 404
    assert client.get("/api/v1/backtests/" + a["id"] + "/report").status_code == 404
    assert client.get("/api/v1/workspaces/" + d["workspace_id"] + "/datasets").status_code == 404


def test_logout_and_login(client):
    h = signup(client)
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    assert client.get("/api/auth/session").status_code == 401
    r = client.post("/api/auth/login", json={"email": "engineer@example.test", "password": "local-demo-password-123"})
    assert r.status_code == 200
    assert client.cookies["strategy_session"]


def test_validation_never_echoes_password(client):
    secret = "private-short"
    r = client.post("/api/auth/register", json={"email": "bad", "password": secret, "unknown": secret})
    assert r.status_code == 422
    assert secret not in json.dumps(r.json())


def test_auth_rate_limit(client):
    _attempts.clear()
    for _ in range(20):
        assert (
            client.post(
                "/api/auth/login", json={"email": "none@example.test", "password": "local-demo-password-123"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"email": "none@example.test", "password": "local-demo-password-123"}
        ).status_code
        == 429
    )


def test_dataset_roundtrip_dedup_and_failed_commit(client):
    h, d, a = demo(client)
    path = f"/api/v1/workspaces/{d['workspace_id']}/datasets"
    original = client.get(path).json()[0]
    payload = {k: original[k] for k in ["source", "venue", "quote_currency", "coverage_end", "candles"]}
    h["Idempotency-Key"] = "copy1"
    r = client.post(path, json=payload, headers=h)
    assert r.status_code == 201
    h["Idempotency-Key"] = "copy2"
    again = client.post(path, json=payload, headers=h)
    assert again.json()["id"] == r.json()["id"]
    count = len(client.get(path).json())
    payload["candles"].pop(3)
    h["Idempotency-Key"] = "bad"
    assert client.post(path, json=payload, headers=h).status_code == 422
    assert len(client.get(path).json()) == count


def test_compare_saved_strategies(client):
    h, d, a = demo(client)
    h["Idempotency-Key"] = "rsi-run"
    b = client.post(
        f"/api/v1/workspaces/{d['workspace_id']}/backtests",
        headers=h,
        json=dict(
            dataset_id=d["dataset_id"],
            market_id=d["market_id"],
            start_date=d["start_date"],
            end_date=d["end_date"],
            strategy="rsi_reversion",
        ),
    )
    assert b.status_code == 201, b.text
    r = client.post("/api/v1/comparisons", headers=h, json={"backtest_ids": [a["id"], b.json()["id"]]})
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 2
    assert r.json()["varying_cost_assumptions"] is False


def test_comparison_rejects_different_initial_cash(client):
    h, d, a = demo(client)
    h["Idempotency-Key"] = "different-size"
    b = client.post(
        f"/api/v1/workspaces/{d['workspace_id']}/backtests",
        headers=h,
        json=dict(
            dataset_id=d["dataset_id"],
            market_id=d["market_id"],
            start_date=d["start_date"],
            end_date=d["end_date"],
            initial_cash="20000",
        ),
    )
    assert b.status_code == 201
    assert (
        client.post("/api/v1/comparisons", headers=h, json={"backtest_ids": [a["id"], b.json()["id"]]}).status_code
        == 422
    )


def test_comparison_rejects_duplicate_ids(client):
    h, d, a = demo(client)
    assert client.post("/api/v1/comparisons", headers=h, json={"backtest_ids": [a["id"], a["id"]]}).status_code == 422


def test_comparison_accepts_numeric_equivalence_and_flags_cost_change(client):
    h, d, a = demo(client)
    h["Idempotency-Key"] = "same-size-different-cost"
    b = client.post(
        f"/api/v1/workspaces/{d['workspace_id']}/backtests",
        headers=h,
        json=dict(
            dataset_id=d["dataset_id"],
            market_id=d["market_id"],
            start_date=d["start_date"],
            end_date=d["end_date"],
            initial_cash="10000.0",
            fee_rate="0.002",
        ),
    )
    assert b.status_code == 201
    r = client.post("/api/v1/comparisons", headers=h, json={"backtest_ids": [a["id"], b.json()["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["varying_cost_assumptions"] is True
