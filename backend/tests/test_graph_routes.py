from __future__ import annotations

from datetime import date
from uuid import UUID

from app.dependencies import graph_service
from app.domain.enums import AssetStatus, AssetType
from app.domain.models import (
    AssetResolution,
    CompanyFilingTarget,
    CompanyFilings,
    CompanyMetadata,
    CompanyMetadataTarget,
    EtfHolding,
    ExposurePath,
    FilingEvidence,
    FilingEvidenceBatch,
    FilingEvidenceTarget,
    SecFiling,
    StructuralExposureItem,
)
from app.providers.base import (
    AssetDataProvider,
    CompanyFilingsProvider,
    CompanyMetadataProvider,
    EtfHoldingsProvider,
    FilingEvidenceProvider,
)
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




class FakeCompanyMetadataProvider(CompanyMetadataProvider):
    def get_metadata(self, cik: str) -> CompanyMetadata | None:
        if cik != "0001045810":
            return None
        return CompanyMetadata(
            cik=cik,
            industry_code="3674",
            industry_name="Semiconductors & Related Devices",
            country_code="X1",
            country_name="UNITED STATES",
            source_url="https://data.sec.gov/submissions/CIK0001045810.json",
        )


class FakeCompanyFilingsProvider(CompanyFilingsProvider):
    def get_recent_filings(self, cik: str, limit: int) -> CompanyFilings | None:
        if cik != "0001045810":
            return None
        filing = SecFiling(
            cik=cik,
            accession_number="0001045810-26-000001",
            form="10-K",
            filing_date=date(2026, 2, 25),
            report_date=date(2026, 1, 25),
            primary_document="nvda-20260125.htm",
            source_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda-20260125.htm",
            filing_index_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/0001045810-26-000001-index.html",
            submissions_url="https://data.sec.gov/submissions/CIK0001045810.json",
        )
        return CompanyFilings(
            cik=cik,
            source_url="https://data.sec.gov/submissions/CIK0001045810.json",
            filings=[filing][:limit],
        )


class FakeFilingEvidenceProvider(FilingEvidenceProvider):
    def extract_evidence(
        self,
        filing: FilingEvidenceTarget,
        limit: int,
    ) -> FilingEvidenceBatch | None:
        evidence = FilingEvidence(
            evidence_id=f"{filing.accession_number}:evidence-1",
            accession_number=filing.accession_number,
            evidence_type="dependency_candidate",
            evidence_text="We depend on suppliers for manufacturing capacity.",
            matched_terms=["depend on", "suppliers"],
            source_url=filing.source_url,
            source_date=filing.filing_date,
            extraction_method="sec_html_dependency_keywords_v1",
        )
        return FilingEvidenceBatch(
            accession_number=filing.accession_number,
            source_url=filing.source_url,
            extraction_method="sec_html_dependency_keywords_v1",
            evidence=[evidence][:limit],
        )


class FakeGraphRepository(GraphRepository):
    def __init__(self) -> None:
        self.metadata_synced = {}

    def sync_portfolio(self, portfolio, etf_holdings, company_resolutions) -> None:
        self.portfolio = portfolio
        self.etf_holdings = dict(etf_holdings)
        self.company_resolutions = dict(company_resolutions)

    def get_company_metadata_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[CompanyMetadataTarget]:
        return [
            CompanyMetadataTarget(cik="0001045810", name="NVIDIA CORP")
        ][:limit]

    def sync_company_metadata(self, company_metadata) -> None:
        self.metadata_synced = dict(company_metadata)

    def get_company_filing_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[CompanyFilingTarget]:
        return [CompanyFilingTarget(cik="0001045810", name="NVIDIA CORP")][:limit]

    def sync_company_filings(self, company_filings) -> None:
        self.filings_synced = dict(company_filings)

    def get_filing_evidence_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[FilingEvidenceTarget]:
        return [
            FilingEvidenceTarget(
                accession_number="0001045810-26-000001",
                cik="0001045810",
                form="10-K",
                filing_date=date(2026, 2, 25),
                source_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda-20260125.htm",
            )
        ][:limit]

    def sync_filing_evidence(self, evidence_batches) -> None:
        self.evidence_synced = dict(evidence_batches)

    def get_exposure_paths(self, portfolio_id: UUID) -> list[ExposurePath]:
        return [
            ExposurePath(
                asset_path=["QQQ", "NVDA"],
                relations=["OWNS", "HOLDS"],
                effective_weight_pct=2.4,
            )
        ]

    def get_industry_exposures(
        self, portfolio_id: UUID
    ) -> list[StructuralExposureItem]:
        return [
            StructuralExposureItem(
                code="3674",
                name="Semiconductors & Related Devices",
                weight_pct=72.4,
            )
        ]

    def get_country_exposures(
        self, portfolio_id: UUID
    ) -> list[StructuralExposureItem]:
        return [
            StructuralExposureItem(
                code="X1",
                name="UNITED STATES",
                weight_pct=72.4,
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
    original_metadata_provider = graph_service.company_metadata_provider
    original_filings_provider = graph_service.company_filings_provider
    original_evidence_provider = graph_service.filing_evidence_provider
    graph_service.graph_repository = FakeGraphRepository()
    graph_service.etf_holdings_provider = FakeEtfHoldingsProvider()
    graph_service.company_asset_provider = FakeCompanyAssetProvider()
    graph_service.company_metadata_provider = FakeCompanyMetadataProvider()
    graph_service.company_filings_provider = FakeCompanyFilingsProvider()
    graph_service.filing_evidence_provider = FakeFilingEvidenceProvider()
    try:
        sync_response = client.post(
            f"/api/v1/portfolios/{portfolio_id}/graph/sync"
        )
        metadata_response = client.post(
            f"/api/v1/portfolios/{portfolio_id}/graph/company-metadata/sync?limit=1"
        )
        filings_response = client.post(
            f"/api/v1/portfolios/{portfolio_id}/graph/sec-filings/sync?company_limit=1&filings_per_company=1"
        )
        evidence_response = client.post(
            f"/api/v1/portfolios/{portfolio_id}/graph/filing-evidence/sync?filing_limit=1&evidence_per_filing=1"
        )
        paths_response = client.get(
            f"/api/v1/portfolios/{portfolio_id}/graph/paths"
        )
        structural_response = client.get(
            f"/api/v1/portfolios/{portfolio_id}/graph/structural-exposure"
        )
    finally:
        graph_service.graph_repository = original_repository
        graph_service.etf_holdings_provider = original_etf_provider
        graph_service.company_asset_provider = original_company_provider
        graph_service.company_metadata_provider = original_metadata_provider
        graph_service.company_filings_provider = original_filings_provider
        graph_service.filing_evidence_provider = original_evidence_provider

    assert sync_response.status_code == 200
    assert sync_response.json()["ownership_edges_synced"] == 2
    assert sync_response.json()["holding_edges_synced"] == 1
    assert sync_response.json()["companies_synced"] == 1
    assert sync_response.json()["represents_edges_synced"] == 1
    assert sync_response.json()["unresolved_company_assets"] == []

    assert metadata_response.status_code == 200
    assert metadata_response.json()["companies_requested"] == 1
    assert metadata_response.json()["companies_enriched"] == 1
    assert metadata_response.json()["industry_edges_synced"] == 1
    assert metadata_response.json()["country_edges_synced"] == 1
    assert metadata_response.json()["unresolved_company_ciks"] == []

    assert filings_response.status_code == 200
    assert filings_response.json() == {
        "portfolio_id": portfolio_id,
        "companies_requested": 1,
        "companies_synced": 1,
        "filings_synced": 1,
        "unresolved_company_ciks": [],
    }

    assert evidence_response.status_code == 200
    assert evidence_response.json() == {
        "portfolio_id": portfolio_id,
        "filings_requested": 1,
        "filings_processed": 1,
        "filings_with_evidence": 1,
        "evidence_synced": 1,
        "filings_without_evidence": [],
        "unresolved_filing_accessions": [],
    }

    assert paths_response.status_code == 200
    assert paths_response.json()["paths"] == [
        {
            "asset_path": ["QQQ", "NVDA"],
            "relations": ["OWNS", "HOLDS"],
            "effective_weight_pct": 2.4,
        }
    ]
    assert structural_response.status_code == 200
    assert structural_response.json() == {
        "portfolio_id": portfolio_id,
        "industries": [
            {
                "code": "3674",
                "name": "Semiconductors & Related Devices",
                "weight_pct": 72.4,
            }
        ],
        "countries": [
            {
                "code": "X1",
                "name": "UNITED STATES",
                "weight_pct": 72.4,
            }
        ],
        "industry_coverage_pct": 72.4,
        "country_coverage_pct": 72.4,
        "industry_basis": "SEC primary SIC",
        "country_basis": "SEC business address",
    }
