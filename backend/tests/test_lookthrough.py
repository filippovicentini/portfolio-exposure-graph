from app.dependencies import lookthrough_service
from app.domain.models import EtfHolding
from app.providers.base import EtfHoldingsProvider


class FakeEtfHoldingsProvider(EtfHoldingsProvider):
    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        assert ticker == "QQQ"
        return [
            EtfHolding(ticker="NVDA", description="NVIDIA", weight_pct=8),
            EtfHolding(ticker="AAPL", description="Apple", weight_pct=7),
        ]


class FailingEtfHoldingsProvider(EtfHoldingsProvider):
    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        raise RuntimeError("provider unavailable")


def test_lookthrough_combines_direct_and_indirect_exposure(client):
    original_provider = lookthrough_service.etf_holdings_provider
    lookthrough_service.etf_holdings_provider = FakeEtfHoldingsProvider()
    try:
        created = client.post(
            "/api/v1/portfolios",
            json={
                "name": "Lookthrough",
                "positions": [
                    {"ticker": "NVDA", "weight_pct": 70},
                    {"ticker": "QQQ", "weight_pct": 30},
                ],
            },
        ).json()

        response = client.get(
            f"/api/v1/portfolios/{created['portfolio_id']}/lookthrough"
        )
    finally:
        lookthrough_service.etf_holdings_provider = original_provider

    assert response.status_code == 200
    body = response.json()
    exposures = {item["ticker"]: item for item in body["exposures"]}

    assert exposures["NVDA"] == {
        "ticker": "NVDA",
        "direct_weight_pct": 70.0,
        "indirect_weight_pct": 2.4,
        "total_weight_pct": 72.4,
        "via_etfs": ["QQQ"],
    }
    assert exposures["AAPL"]["direct_weight_pct"] == 0.0
    assert exposures["AAPL"]["indirect_weight_pct"] == 2.1
    assert exposures["AAPL"]["total_weight_pct"] == 2.1
    assert body["unexpanded_etfs"] == []


def test_lookthrough_reports_etf_that_cannot_be_expanded(client):
    original_provider = lookthrough_service.etf_holdings_provider
    lookthrough_service.etf_holdings_provider = FailingEtfHoldingsProvider()
    try:
        created = client.post(
            "/api/v1/portfolios",
            json={
                "name": "ETF only",
                "positions": [{"ticker": "QQQ", "weight_pct": 100}],
            },
        ).json()

        response = client.get(
            f"/api/v1/portfolios/{created['portfolio_id']}/lookthrough"
        )
    finally:
        lookthrough_service.etf_holdings_provider = original_provider

    assert response.status_code == 200
    assert response.json()["exposures"] == []
    assert response.json()["unexpanded_etfs"] == ["QQQ"]
