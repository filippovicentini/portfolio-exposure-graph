from __future__ import annotations

from uuid import UUID

from app.domain.models import EtfHolding, ExposurePath
from app.providers.base import EtfHoldingsProvider
from app.repositories.graph_repository import GraphRepository
from app.services.graph_service import GraphService


class FakeEtfHoldingsProvider(EtfHoldingsProvider):
    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        assert ticker == "QQQ"
        return [
            EtfHolding(ticker="NVDA", description="NVIDIA", weight_pct=8.0),
            EtfHolding(ticker="AAPL", description="Apple", weight_pct=7.0),
            EtfHolding(ticker="ZERO", description="Zero weight", weight_pct=0.0),
        ]


class FakeGraphRepository(GraphRepository):
    def __init__(self) -> None:
        self.synced_portfolio = None
        self.synced_holdings = None

    def sync_portfolio(self, portfolio, etf_holdings) -> None:
        self.synced_portfolio = portfolio
        self.synced_holdings = dict(etf_holdings)

    def get_exposure_paths(self, portfolio_id: UUID) -> list[ExposurePath]:
        return [
            ExposurePath(
                asset_path=["NVDA"],
                relations=["OWNS"],
                effective_weight_pct=70.0,
            ),
            ExposurePath(
                asset_path=["QQQ", "NVDA"],
                relations=["OWNS", "HOLDS"],
                effective_weight_pct=2.4,
            ),
        ]


def test_graph_service_syncs_direct_and_etf_exposure(client, portfolio_repository):
    created = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Graph test",
            "positions": [
                {"ticker": "NVDA", "weight_pct": 70},
                {"ticker": "QQQ", "weight_pct": 30},
            ],
        },
    ).json()
    portfolio_id = UUID(created["portfolio_id"])

    graph_repository = FakeGraphRepository()
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
    )

    result = service.sync(portfolio_id)

    assert result is not None
    assert result.assets_synced == 3
    assert result.ownership_edges_synced == 2
    assert result.holding_edges_synced == 2
    assert result.unexpanded_etfs == []
    assert graph_repository.synced_portfolio.portfolio_id == portfolio_id
    assert [holding.ticker for holding in graph_repository.synced_holdings["QQQ"]] == [
        "NVDA",
        "AAPL",
    ]


def test_graph_service_returns_paths(client, portfolio_repository):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Paths", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])

    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=FakeGraphRepository(),
        etf_holdings_provider=FakeEtfHoldingsProvider(),
    )

    result = service.get_paths(portfolio_id)

    assert result is not None
    assert result.paths[0].asset_path == ["NVDA"]
    assert result.paths[1].asset_path == ["QQQ", "NVDA"]
    assert result.paths[1].effective_weight_pct == 2.4
