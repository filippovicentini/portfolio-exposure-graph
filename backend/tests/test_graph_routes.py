from __future__ import annotations

from uuid import UUID

from app.dependencies import graph_service
from app.domain.models import EtfHolding, ExposurePath
from app.providers.base import EtfHoldingsProvider
from app.repositories.graph_repository import GraphRepository


class FakeEtfHoldingsProvider(EtfHoldingsProvider):
    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        assert ticker == "QQQ"
        return [EtfHolding(ticker="NVDA", description="NVIDIA", weight_pct=8.0)]


class FakeGraphRepository(GraphRepository):
    def sync_portfolio(self, portfolio, etf_holdings) -> None:
        self.portfolio = portfolio
        self.etf_holdings = dict(etf_holdings)

    def get_exposure_paths(self, portfolio_id: UUID) -> list[ExposurePath]:
        return [
            ExposurePath(
                asset_path=["QQQ", "NVDA"],
                relations=["OWNS", "HOLDS"],
                effective_weight_pct=2.4,
            )
        ]


def test_graph_sync_and_paths_endpoints(client):
    created = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Graph API",
            "positions": [
                {"ticker": "NVDA", "weight_pct": 70},
                {"ticker": "QQQ", "weight_pct": 30},
            ],
        },
    ).json()
    portfolio_id = created["portfolio_id"]

    original_repository = graph_service.graph_repository
    original_provider = graph_service.etf_holdings_provider
    graph_service.graph_repository = FakeGraphRepository()
    graph_service.etf_holdings_provider = FakeEtfHoldingsProvider()
    try:
        sync_response = client.post(
            f"/api/v1/portfolios/{portfolio_id}/graph/sync"
        )
        paths_response = client.get(
            f"/api/v1/portfolios/{portfolio_id}/graph/paths"
        )
    finally:
        graph_service.graph_repository = original_repository
        graph_service.etf_holdings_provider = original_provider

    assert sync_response.status_code == 200
    assert sync_response.json()["ownership_edges_synced"] == 2
    assert sync_response.json()["holding_edges_synced"] == 1

    assert paths_response.status_code == 200
    assert paths_response.json()["paths"] == [
        {
            "asset_path": ["QQQ", "NVDA"],
            "relations": ["OWNS", "HOLDS"],
            "effective_weight_pct": 2.4,
        }
    ]
