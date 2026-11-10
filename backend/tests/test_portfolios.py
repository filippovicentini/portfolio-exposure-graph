def test_create_portfolio_with_known_assets_is_ready(client):
    response = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Core",
            "positions": [
                {"ticker": "NVDA", "weight_pct": 60},
                {"ticker": "QQQ", "weight_pct": 40},
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["enrichment_jobs"] == []
    assert body["positions"][0]["asset"]["asset_type"] == "equity"
    assert body["positions"][1]["asset"]["asset_type"] == "etf"


def test_unknown_ticker_is_queued_without_blocking_portfolio_creation(client):
    response = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Mixed",
            "positions": [
                {"ticker": "NVDA", "weight_pct": 70},
                {"ticker": "ASML", "weight_pct": 30},
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "partially_ready"
    assert body["positions"][1]["asset"]["status"] == "pending_enrichment"
    assert body["enrichment_jobs"][0]["ticker"] == "ASML"
    assert body["enrichment_jobs"][0]["status"] == "queued"


def test_weights_must_sum_to_100(client):
    response = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Broken",
            "positions": [
                {"ticker": "NVDA", "weight_pct": 30},
                {"ticker": "MSFT", "weight_pct": 30},
            ],
        },
    )

    assert response.status_code == 422


def test_duplicate_tickers_are_rejected(client):
    response = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Duplicate",
            "positions": [
                {"ticker": "nvda", "weight_pct": 50},
                {"ticker": "NVDA", "weight_pct": 50},
            ],
        },
    )

    assert response.status_code == 422


def test_list_portfolios_returns_newest_first(client):
    for name in ("First", "Second"):
        response = client.post(
            "/api/v1/portfolios",
            json={"name": name, "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
        )
        assert response.status_code == 201

    response = client.get("/api/v1/portfolios")

    assert response.status_code == 200
    assert [portfolio["name"] for portfolio in response.json()] == ["Second", "First"]

    limited = client.get("/api/v1/portfolios", params={"limit": 1})
    assert [portfolio["name"] for portfolio in limited.json()] == ["Second"]


def test_unknown_portfolio_store_is_rejected(monkeypatch):
    import pytest

    from app import dependencies

    monkeypatch.setattr(dependencies.settings, "portfolio_store", "sqlite")

    with pytest.raises(ValueError, match="PORTFOLIO_STORE"):
        dependencies.build_portfolio_repository()
