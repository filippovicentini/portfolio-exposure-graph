from __future__ import annotations

from uuid import UUID

from app.dependencies import graph_service
from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution, EtfHolding, ExposurePath
from app.providers.base import AssetDataProvider, EtfHoldingsProvider
from app.repositories.graph_repository import GraphRepository


class FakeEtfHoldingsProvider(EtfHoldingsProvider):
    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        assert ticker == "QQQ"
        return [EtfHolding(ticker="NVDA", description="NVIDIA", weight_pct=8.0)]


class FakeCompanyAssetProvider(AssetDataProvider):
    def resolve(self, ticker: str) -> AssetResolution | None:
        if ticker != "NVDA":
            return None
        return AssetResolution(
            ticker="NVDA",
            exchange="Nasdaq",
            asset_type=AssetType.EQUITY,
            status=AssetStatus.READY,
            company_name="NVIDIA CORP",
            cik="0001045810",
        )


class FakeGraphRepository(GraphRepository):
    def sync_portfolio(self, portfolio, etf_holdings, company_resolutions) -> None:
        self.portfolio = portfolio
        self.etf_holdings = dict(etf_holdings)
        self.company_resolutions = dict(company_resolutions)

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
    original_etf_provider = graph_service.etf_holdings_provider
    original_company_provider = graph_service.company_asset_provider
    graph_service.graph_repository = FakeGraphRepository()
    graph_service.etf_holdings_provider = FakeEtfHoldingsProvider()
    graph_service.company_asset_provider = FakeCompanyAssetProvider()
    try:
        sync_response = client.post(
            f"/api/v1/portfolios/{portfolio_id}/graph/sync"
        )
        paths_response = client.get(
            f"/api/v1/portfolios/{portfolio_id}/graph/paths"
        )
    finally:
        graph_service.graph_repository = original_repository
        graph_service.etf_holdings_provider = original_etf_provider
        graph_service.company_asset_provider = original_company_provider

    assert sync_response.status_code == 200
    assert sync_response.json()["ownership_edges_synced"] == 2
    assert sync_response.json()["holding_edges_synced"] == 1
    assert sync_response.json()["companies_synced"] == 1
    assert sync_response.json()["represents_edges_synced"] == 1
    assert sync_response.json()["unresolved_company_assets"] == []

    assert paths_response.status_code == 200
    assert paths_response.json()["paths"] == [
        {
            "asset_path": ["QQQ", "NVDA"],
            "relations": ["OWNS", "HOLDS"],
            "effective_weight_pct": 2.4,
        }
    ]
