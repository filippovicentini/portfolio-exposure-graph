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
