from __future__ import annotations

from uuid import UUID

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import (
    AssetResolution,
    CompanyMetadata,
    CompanyMetadataTarget,
    EtfHolding,
    ExposurePath,
    StructuralExposureItem,
)
from app.providers.base import (
    AssetDataProvider,
    CompanyMetadataProvider,
    EtfHoldingsProvider,
)
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


class FakeCompanyAssetProvider(AssetDataProvider):
    def resolve(self, ticker: str) -> AssetResolution | None:
        companies = {
            "NVDA": ("NVIDIA CORP", "0001045810", "Nasdaq"),
            "AAPL": ("Apple Inc.", "0000320193", "Nasdaq"),
        }
        data = companies.get(ticker)
        if data is None:
            return None
        name, cik, exchange = data
        return AssetResolution(
            ticker=ticker,
            exchange=exchange,
            asset_type=AssetType.EQUITY,
            status=AssetStatus.READY,
            company_name=name,
            cik=cik,
        )


class FailingCompanyAssetProvider(AssetDataProvider):
    def resolve(self, ticker: str) -> AssetResolution | None:
        raise RuntimeError("provider unavailable")


class FakeCompanyMetadataProvider(CompanyMetadataProvider):
    def get_metadata(self, cik: str) -> CompanyMetadata | None:
        metadata = {
            "0001045810": CompanyMetadata(
                cik="0001045810",
                industry_code="3674",
                industry_name="Semiconductors & Related Devices",
                country_code="X1",
                country_name="UNITED STATES",
                source_url="https://data.sec.gov/submissions/CIK0001045810.json",
            ),
            "0000320193": CompanyMetadata(
                cik="0000320193",
                industry_code="3571",
                industry_name="Electronic Computers",
                country_code="X1",
                country_name="UNITED STATES",
                source_url="https://data.sec.gov/submissions/CIK0000320193.json",
            ),
        }
        return metadata.get(cik)


class FailingCompanyMetadataProvider(CompanyMetadataProvider):
    def get_metadata(self, cik: str) -> CompanyMetadata | None:
        raise RuntimeError("metadata unavailable")


class FakeGraphRepository(GraphRepository):
    def __init__(self) -> None:
        self.synced_portfolio = None
        self.synced_holdings = None
        self.synced_companies = None
        self.metadata_targets: list[CompanyMetadataTarget] = []
        self.synced_metadata = None

    def sync_portfolio(self, portfolio, etf_holdings, company_resolutions) -> None:
        self.synced_portfolio = portfolio
        self.synced_holdings = dict(etf_holdings)
        self.synced_companies = dict(company_resolutions)

    def get_company_metadata_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[CompanyMetadataTarget]:
        return self.metadata_targets[:limit]

    def sync_company_metadata(self, company_metadata) -> None:
        self.synced_metadata = dict(company_metadata)

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

    def get_industry_exposures(
        self, portfolio_id: UUID
    ) -> list[StructuralExposureItem]:
        return [
            StructuralExposureItem(
                code="3674",
                name="Semiconductors & Related Devices",
                weight_pct=72.4,
            ),
            StructuralExposureItem(
                code="3571",
                name="Electronic Computers",
                weight_pct=2.1,
            ),
        ]

    def get_country_exposures(
        self, portfolio_id: UUID
    ) -> list[StructuralExposureItem]:
        return [
            StructuralExposureItem(
                code="X1",
                name="UNITED STATES",
                weight_pct=74.5,
            )
        ]


def test_graph_service_syncs_assets_etf_exposure_and_companies(
    client, portfolio_repository
):
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
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
    )

    result = service.sync(portfolio_id)

    assert result is not None
    assert result.assets_synced == 3
    assert result.companies_synced == 2
    assert result.ownership_edges_synced == 2
    assert result.holding_edges_synced == 2
    assert result.represents_edges_synced == 2
    assert result.unexpanded_etfs == []
    assert result.unresolved_company_assets == []
    assert graph_repository.synced_portfolio.portfolio_id == portfolio_id
    assert [holding.ticker for holding in graph_repository.synced_holdings["QQQ"]] == [
        "NVDA",
        "AAPL",
    ]
    assert set(graph_repository.synced_companies) == {"AAPL", "NVDA"}
    assert graph_repository.synced_companies["NVDA"].cik == "0001045810"


def test_graph_service_keeps_graph_sync_available_when_company_provider_fails(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Fallback", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FailingCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
    )

    result = service.sync(portfolio_id)

    assert result is not None
    assert result.assets_synced == 1
    assert result.companies_synced == 0
    assert result.represents_edges_synced == 0
    assert result.unresolved_company_assets == ["NVDA"]
    assert graph_repository.synced_companies == {}


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
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
    )

    result = service.get_paths(portfolio_id)

    assert result is not None
    assert result.paths[0].asset_path == ["NVDA"]
    assert result.paths[1].asset_path == ["QQQ", "NVDA"]
    assert result.paths[1].effective_weight_pct == 2.4


def test_graph_service_returns_structural_exposure_breakdown(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Structural", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])

    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=FakeGraphRepository(),
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
    )

    result = service.get_structural_exposure(portfolio_id)

    assert result is not None
    assert result.industries[0].code == "3674"
    assert result.industries[0].weight_pct == 72.4
    assert result.countries[0].code == "X1"
    assert result.industry_coverage_pct == 74.5
    assert result.country_coverage_pct == 74.5
    assert result.industry_basis == "SEC primary SIC"
    assert result.country_basis == "SEC business address"

def test_graph_service_syncs_company_metadata_in_bounded_batches(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Metadata", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.metadata_targets = [
        CompanyMetadataTarget(cik="0001045810", name="NVIDIA CORP"),
        CompanyMetadataTarget(cik="0000320193", name="Apple Inc."),
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
    )

    result = service.sync_company_metadata(portfolio_id, limit=1)

    assert result is not None
    assert result.companies_requested == 1
    assert result.companies_enriched == 1
    assert result.industry_edges_synced == 1
    assert result.country_edges_synced == 1
    assert result.unresolved_company_ciks == []
    assert set(graph_repository.synced_metadata) == {"0001045810"}


def test_graph_service_company_metadata_failures_are_non_blocking(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Metadata fallback", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.metadata_targets = [
        CompanyMetadataTarget(cik="0001045810", name="NVIDIA CORP")
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FailingCompanyMetadataProvider(),
    )

    result = service.sync_company_metadata(portfolio_id)

    assert result is not None
    assert result.companies_requested == 1
    assert result.companies_enriched == 0
    assert result.industry_edges_synced == 0
    assert result.country_edges_synced == 0
    assert result.unresolved_company_ciks == ["0001045810"]
    assert graph_repository.synced_metadata == {}
