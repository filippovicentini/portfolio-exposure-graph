def test_invalid_ticker_is_rejected(client):
    response = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Bad",
            "positions": [
                {"ticker": "NVDA", "weight_pct": 70},
                {"ticker": "@@@", "weight_pct": 30},
            ],
        },
    )

    assert response.status_code == 422
    assert "Invalid ticker '@@@'" in response.text


def test_ticker_with_class_suffix_is_accepted(client):
    response = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Classes",
            "positions": [
                {"ticker": " brk.b ", "weight_pct": 50},
                {"ticker": "BF-B", "weight_pct": 50},
            ],
        },
    )

    assert response.status_code == 201
    assert [p["ticker"] for p in response.json()["positions"]] == ["BRK.B", "BF-B"]
