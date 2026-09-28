from __future__ import annotations

from datetime import date
from uuid import UUID

from app.domain.enums import AssetStatus, AssetType, CandidateRelationType, CandidateRole
from app.domain.models import (
    AssetResolution,
    CandidateEntityResolutionTarget,
    DependencyPromotionTarget,
    CompanyFilingTarget,
    CompanyFilings,
    CompanyMetadata,
    CompanyMetadataTarget,
    EvidenceSemanticCandidateBatch,
    EvidenceSemanticTarget,
    EtfHolding,
    ExposurePath,
    FilingEvidence,
    FilingEvidenceBatch,
    FilingEvidenceTarget,
    RelationshipCandidate,
    SecFiling,
    StructuralExposureItem,
    SupplierIdentity,
)
from app.providers.base import (
    AssetDataProvider,
    CompanyFilingsProvider,
    CompanyMetadataProvider,
    EvidenceSemanticCandidateProvider,
    EtfHoldingsProvider,
    FilingEvidenceProvider,
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


class FakeCompanyFilingsProvider(CompanyFilingsProvider):
    def get_recent_filings(self, cik: str, limit: int) -> CompanyFilings | None:
        filings = {
            "0001045810": [
                SecFiling(
                    cik="0001045810",
                    accession_number="0001045810-26-000001",
                    form="10-K",
                    filing_date=date(2026, 2, 25),
                    report_date=date(2026, 1, 25),
                    primary_document="nvda-20260125.htm",
                    source_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda-20260125.htm",
                    filing_index_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/0001045810-26-000001-index.html",
                    submissions_url="https://data.sec.gov/submissions/CIK0001045810.json",
                ),
                SecFiling(
                    cik="0001045810",
                    accession_number="0001045810-25-000200",
                    form="10-Q",
                    filing_date=date(2025, 11, 19),
                    report_date=date(2025, 10, 26),
                    primary_document="nvda-20251026.htm",
                    source_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581025000200/nvda-20251026.htm",
                    filing_index_url="https://www.sec.gov/Archives/edgar/data/1045810/0001045810-25-000200-index.html",
                    submissions_url="https://data.sec.gov/submissions/CIK0001045810.json",
                ),
            ]
        }
        company_filings = filings.get(cik)
        if company_filings is None:
            return None
        return CompanyFilings(
            cik=cik,
            source_url=f"https://data.sec.gov/submissions/CIK{cik}.json",
            filings=company_filings[:limit],
        )


class FailingCompanyFilingsProvider(CompanyFilingsProvider):
    def get_recent_filings(self, cik: str, limit: int) -> CompanyFilings | None:
        raise RuntimeError("filings unavailable")


class FakeFilingEvidenceProvider(FilingEvidenceProvider):
    def extract_evidence(
        self,
        filing: FilingEvidenceTarget,
        limit: int,
    ) -> FilingEvidenceBatch | None:
        evidence = [
            FilingEvidence(
                evidence_id=f"{filing.accession_number}:evidence-1",
                accession_number=filing.accession_number,
                evidence_type="dependency_candidate",
                evidence_text="We depend on third-party suppliers for critical manufacturing capacity.",
                matched_terms=["depend on", "suppliers"],
                source_url=filing.source_url,
                source_date=filing.filing_date,
                extraction_method="sec_html_dependency_keywords_v1",
            )
        ]
        return FilingEvidenceBatch(
            accession_number=filing.accession_number,
            source_url=filing.source_url,
            extraction_method="sec_html_dependency_keywords_v1",
            evidence=evidence[:limit],
        )


class FailingFilingEvidenceProvider(FilingEvidenceProvider):
    def extract_evidence(
        self,
        filing: FilingEvidenceTarget,
        limit: int,
    ) -> FilingEvidenceBatch | None:
        raise RuntimeError("filing text unavailable")


class FakeEvidenceSemanticCandidateProvider(EvidenceSemanticCandidateProvider):
    def extract_candidates(
        self,
        evidence: EvidenceSemanticTarget,
        limit: int,
    ) -> EvidenceSemanticCandidateBatch | None:
        candidates = [
            RelationshipCandidate(
                candidate_id=f"{evidence.evidence_id}:tsmc",
                evidence_id=evidence.evidence_id,
                subject_cik=evidence.subject_cik,
                subject_name=evidence.subject_name,
                object_mention="Taiwan Semiconductor Manufacturing Company Limited",
                proposed_relation=CandidateRelationType.DEPENDS_ON,
                role=CandidateRole.FOUNDRY,
                supporting_text=evidence.evidence_text,
                extraction_method="fake_semantic_v1",
                model_name="fake-model",
            )
        ]
        return EvidenceSemanticCandidateBatch(
            evidence_id=evidence.evidence_id,
            extraction_method="fake_semantic_v1",
            model_name="fake-model",
            candidates=candidates[:limit],
        )


class FailingEvidenceSemanticCandidateProvider(EvidenceSemanticCandidateProvider):
    def extract_candidates(
        self,
        evidence: EvidenceSemanticTarget,
        limit: int,
    ) -> EvidenceSemanticCandidateBatch | None:
        raise RuntimeError("semantic provider unavailable")


class FakeGraphRepository(GraphRepository):
    def __init__(self) -> None:
        self.synced_portfolio = None
        self.synced_holdings = None
        self.synced_companies = None
        self.metadata_targets: list[CompanyMetadataTarget] = []
        self.synced_metadata = None
        self.filing_targets: list[CompanyFilingTarget] = []
        self.synced_filings = None
        self.evidence_targets: list[FilingEvidenceTarget] = []
        self.synced_evidence = None
        self.semantic_targets: list[EvidenceSemanticTarget] = []
        self.synced_semantic_candidates = None
        self.entity_resolution_targets: list[CandidateEntityResolutionTarget] = []
        self.synced_entity_resolutions = None
        self.dependency_promotion_targets: list[DependencyPromotionTarget] = []
        self.synced_dependency_promotions = None
        self.synced_dependency_rejections = None
        self.suppliers_by_alias: dict[str, SupplierIdentity] = {}

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

    def get_company_filing_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[CompanyFilingTarget]:
        return self.filing_targets[:limit]

    def sync_company_filings(self, company_filings) -> None:
        self.synced_filings = dict(company_filings)

    def get_filing_evidence_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[FilingEvidenceTarget]:
        return self.evidence_targets[:limit]

    def sync_filing_evidence(self, evidence_batches) -> None:
        self.synced_evidence = dict(evidence_batches)

    def get_evidence_semantic_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[EvidenceSemanticTarget]:
        return self.semantic_targets[:limit]

    def sync_evidence_semantic_candidates(self, candidate_batches) -> None:
        self.synced_semantic_candidates = dict(candidate_batches)

    def get_candidate_entity_resolution_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[CandidateEntityResolutionTarget]:
        return self.entity_resolution_targets[:limit]

    def get_supplier_by_alias(self, alias: str) -> SupplierIdentity | None:
        return self.suppliers_by_alias.get(alias.casefold())

    def sync_candidate_entity_resolutions(self, resolutions) -> None:
        self.synced_entity_resolutions = list(resolutions)
        for resolution in resolutions:
            for alias in resolution.supplier.aliases:
                self.suppliers_by_alias[alias.casefold()] = resolution.supplier

    def get_dependency_promotion_targets(
        self, portfolio_id: UUID, limit: int
    ) -> list[DependencyPromotionTarget]:
        return self.dependency_promotion_targets[:limit]

    def sync_evidence_backed_dependencies(self, promotions, rejections) -> None:
        self.synced_dependency_promotions = list(promotions)
        self.synced_dependency_rejections = list(rejections)

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
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
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
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
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
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
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
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
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
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
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
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_company_metadata(portfolio_id)

    assert result is not None
    assert result.companies_requested == 1
    assert result.companies_enriched == 0
    assert result.industry_edges_synced == 0
    assert result.country_edges_synced == 0
    assert result.unresolved_company_ciks == ["0001045810"]
    assert graph_repository.synced_metadata == {}


def test_graph_service_syncs_recent_company_filings_in_bounded_batches(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Filings", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.filing_targets = [
        CompanyFilingTarget(cik="0001045810", name="NVIDIA CORP"),
        CompanyFilingTarget(cik="0000320193", name="Apple Inc."),
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_company_filings(
        portfolio_id,
        company_limit=1,
        filings_per_company=1,
    )

    assert result is not None
    assert result.companies_requested == 1
    assert result.companies_synced == 1
    assert result.filings_synced == 1
    assert result.unresolved_company_ciks == []
    assert set(graph_repository.synced_filings) == {"0001045810"}
    assert len(graph_repository.synced_filings["0001045810"].filings) == 1


def test_graph_service_company_filing_failures_are_non_blocking(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Filings fallback", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.filing_targets = [
        CompanyFilingTarget(cik="0001045810", name="NVIDIA CORP")
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FailingCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_company_filings(portfolio_id)

    assert result is not None
    assert result.companies_requested == 1
    assert result.companies_synced == 0
    assert result.filings_synced == 0
    assert result.unresolved_company_ciks == ["0001045810"]
    assert graph_repository.synced_filings == {}


def test_graph_service_syncs_filing_evidence_in_bounded_batches(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Evidence", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.evidence_targets = [
        FilingEvidenceTarget(
            accession_number="0001045810-26-000001",
            cik="0001045810",
            form="10-K",
            filing_date=date(2026, 2, 25),
            source_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda-20260125.htm",
        ),
        FilingEvidenceTarget(
            accession_number="0001045810-25-000200",
            cik="0001045810",
            form="10-Q",
            filing_date=date(2025, 11, 19),
            source_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581025000200/nvda-20251026.htm",
        ),
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_filing_evidence(
        portfolio_id,
        filing_limit=1,
        evidence_per_filing=1,
    )

    assert result is not None
    assert result.filings_requested == 1
    assert result.filings_processed == 1
    assert result.filings_with_evidence == 1
    assert result.evidence_synced == 1
    assert result.filings_without_evidence == []
    assert result.unresolved_filing_accessions == []
    assert set(graph_repository.synced_evidence) == {"0001045810-26-000001"}


def test_graph_service_filing_evidence_failures_are_non_blocking(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Evidence fallback", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.evidence_targets = [
        FilingEvidenceTarget(
            accession_number="0001045810-26-000001",
            cik="0001045810",
            form="10-K",
            filing_date=date(2026, 2, 25),
            source_url="https://example.com/filing.htm",
        )
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FailingFilingEvidenceProvider(),
    )

    result = service.sync_filing_evidence(portfolio_id)

    assert result is not None
    assert result.filings_requested == 1
    assert result.filings_processed == 0
    assert result.filings_with_evidence == 0
    assert result.evidence_synced == 0
    assert result.unresolved_filing_accessions == ["0001045810-26-000001"]
    assert graph_repository.synced_evidence == {}


def test_graph_service_syncs_evidence_semantic_candidates_in_bounded_batches(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Semantic", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.semantic_targets = [
        EvidenceSemanticTarget(
            evidence_id="evidence-1",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            accession_number="0001045810-26-000001",
            evidence_text="We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited.",
            source_url="https://example.com/filing.htm",
            source_date=date(2026, 2, 25),
        ),
        EvidenceSemanticTarget(
            evidence_id="evidence-2",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            accession_number="0001045810-26-000001",
            evidence_text="We purchase memory from SK Hynix.",
            source_url="https://example.com/filing.htm",
            source_date=date(2026, 2, 25),
        ),
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
        semantic_candidate_provider=FakeEvidenceSemanticCandidateProvider(),
    )

    result = service.sync_evidence_semantic_candidates(
        portfolio_id,
        evidence_limit=1,
        candidates_per_evidence=1,
    )

    assert result is not None
    assert result.evidence_requested == 1
    assert result.evidence_processed == 1
    assert result.evidence_with_candidates == 1
    assert result.candidates_synced == 1
    assert result.evidence_without_candidates == []
    assert result.unresolved_evidence_ids == []
    assert set(graph_repository.synced_semantic_candidates) == {"evidence-1"}


def test_graph_service_semantic_candidate_failures_are_non_blocking(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Semantic fallback", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.semantic_targets = [
        EvidenceSemanticTarget(
            evidence_id="evidence-1",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            accession_number="0001045810-26-000001",
            evidence_text="We utilize foundries, such as TSMC.",
            source_url="https://example.com/filing.htm",
            source_date=date(2026, 2, 25),
        )
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
        semantic_candidate_provider=FailingEvidenceSemanticCandidateProvider(),
    )

    result = service.sync_evidence_semantic_candidates(portfolio_id)

    assert result is not None
    assert result.evidence_requested == 1
    assert result.evidence_processed == 0
    assert result.evidence_with_candidates == 0
    assert result.candidates_synced == 0
    assert result.unresolved_evidence_ids == ["evidence-1"]
    assert graph_repository.synced_semantic_candidates == {}


def test_graph_service_without_semantic_provider_leaves_evidence_unprocessed(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Semantic disabled", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.semantic_targets = [
        EvidenceSemanticTarget(
            evidence_id="evidence-1",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            accession_number="0001045810-26-000001",
            evidence_text="We utilize foundries, such as TSMC.",
            source_url="https://example.com/filing.htm",
            source_date=date(2026, 2, 25),
        )
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_evidence_semantic_candidates(portfolio_id)

    assert result is not None
    assert result.evidence_requested == 1
    assert result.evidence_processed == 0
    assert result.unresolved_evidence_ids == ["evidence-1"]
    assert graph_repository.synced_semantic_candidates == {}


def test_graph_service_resolves_candidate_entities_and_deduplicates_aliases(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Entity resolution", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    evidence_text = (
        "We utilize foundries, such as Samsung Electronics Co., Ltd., or Samsung, "
        "to produce our semiconductor wafers. We purchase memory from Samsung."
    )
    graph_repository.entity_resolution_targets = [
        CandidateEntityResolutionTarget(
            candidate_id="candidate-samsung-foundry",
            evidence_id="evidence-1",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            object_mention="Samsung Electronics Co., Ltd.",
            role=CandidateRole.FOUNDRY,
            supporting_text=evidence_text,
            evidence_text=evidence_text,
        ),
        CandidateEntityResolutionTarget(
            candidate_id="candidate-samsung-memory",
            evidence_id="evidence-1",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            object_mention="Samsung",
            role=CandidateRole.MEMORY_SUPPLIER,
            supporting_text=evidence_text,
            evidence_text=evidence_text,
        ),
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_candidate_entity_resolutions(portfolio_id, candidate_limit=2)

    assert result is not None
    assert result.candidates_requested == 2
    assert result.candidates_resolved == 2
    assert result.suppliers_synced == 1
    assert result.unresolved_candidate_ids == []
    assert len(graph_repository.synced_entity_resolutions) == 2
    supplier_ids = {
        resolution.supplier.supplier_id
        for resolution in graph_repository.synced_entity_resolutions
    }
    assert len(supplier_ids) == 1


def test_graph_service_reuses_existing_supplier_alias(client, portfolio_repository):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Existing supplier", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    existing = SupplierIdentity(
        supplier_id="supplier:existing-tsmc",
        canonical_name="Taiwan Semiconductor Manufacturing Company Limited",
        aliases=["Taiwan Semiconductor Manufacturing Company Limited", "TSMC"],
    )
    graph_repository.suppliers_by_alias["tsmc"] = existing
    graph_repository.entity_resolution_targets = [
        CandidateEntityResolutionTarget(
            candidate_id="candidate-tsmc",
            evidence_id="evidence-2",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            object_mention="TSMC",
            role=CandidateRole.FOUNDRY,
            supporting_text="We rely on TSMC for wafer fabrication.",
            evidence_text="We rely on TSMC for wafer fabrication.",
        )
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_candidate_entity_resolutions(portfolio_id)

    assert result is not None
    assert result.candidates_resolved == 1
    assert result.suppliers_synced == 1
    resolution = graph_repository.synced_entity_resolutions[0]
    assert resolution.supplier.supplier_id == "supplier:existing-tsmc"
    assert resolution.supplier.canonical_name == existing.canonical_name


def test_graph_service_promotes_resolved_evidence_candidates_and_deduplicates_edges(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Promotions", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    evidence_text = (
        "We utilize foundries, such as Samsung Electronics Co., Ltd., or Samsung, "
        "to produce our semiconductor wafers. We purchase memory from Samsung."
    )
    common = dict(
        subject_cik="0001045810",
        subject_name="NVIDIA CORP",
        supplier_id="supplier:samsung",
        supplier_canonical_name="Samsung Electronics Co., Ltd.",
        supplier_aliases=["Samsung Electronics Co., Ltd.", "Samsung"],
        proposed_relation=CandidateRelationType.DEPENDS_ON,
        evidence_id="evidence-1",
        evidence_text=evidence_text,
        accession_number="0001045810-26-000001",
        source_url="https://example.com/filing.htm",
        source_date=date(2026, 2, 25),
        extraction_method="ollama_structured_dependency_v1",
        model_name="qwen3:4b-instruct",
        entity_resolution_method="evidence_alias_exact_v1",
    )
    graph_repository.dependency_promotion_targets = [
        DependencyPromotionTarget(
            candidate_id="candidate-samsung-foundry",
            object_mention="Samsung Electronics Co., Ltd.",
            role=CandidateRole.FOUNDRY,
            supporting_text=(
                "We utilize foundries, such as Samsung Electronics Co., Ltd., or Samsung, "
                "to produce our semiconductor wafers."
            ),
            **common,
        ),
        DependencyPromotionTarget(
            candidate_id="candidate-samsung-memory",
            object_mention="Samsung",
            role=CandidateRole.MEMORY_SUPPLIER,
            supporting_text="We purchase memory from Samsung.",
            **common,
        ),
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_evidence_backed_dependencies(portfolio_id, candidate_limit=2)

    assert result is not None
    assert result.candidates_requested == 2
    assert result.candidates_promoted == 2
    assert result.dependency_edges_synced == 1
    assert result.candidates_rejected == 0
    assert result.rejected_candidate_ids == []
    assert result.unresolved_candidate_ids == []
    assert len(graph_repository.synced_dependency_promotions) == 2
    assert graph_repository.synced_dependency_rejections == []


def test_graph_service_marks_deterministic_dependency_rejections(
    client, portfolio_repository
):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Rejected promotion", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    portfolio_id = UUID(created["portfolio_id"])
    graph_repository = FakeGraphRepository()
    graph_repository.dependency_promotion_targets = [
        DependencyPromotionTarget(
            candidate_id="candidate-other",
            subject_cik="0001045810",
            subject_name="NVIDIA CORP",
            supplier_id="supplier:generic",
            supplier_canonical_name="Generic Partner",
            supplier_aliases=["Generic Partner"],
            object_mention="Generic Partner",
            proposed_relation=CandidateRelationType.DEPENDS_ON,
            role=CandidateRole.OTHER,
            supporting_text="We work with Generic Partner.",
            evidence_id="evidence-other",
            evidence_text="We work with Generic Partner.",
            accession_number="0001045810-26-000001",
            source_url="https://example.com/filing.htm",
            source_date=date(2026, 2, 25),
            extraction_method="ollama_structured_dependency_v1",
            model_name="qwen3:4b-instruct",
            entity_resolution_method="evidence_alias_exact_v1",
        )
    ]
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph_repository,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync_evidence_backed_dependencies(portfolio_id)

    assert result is not None
    assert result.candidates_promoted == 0
    assert result.dependency_edges_synced == 0
    assert result.candidates_rejected == 1
    assert result.rejected_candidate_ids == ["candidate-other"]
    assert result.unresolved_candidate_ids == []
    assert graph_repository.synced_dependency_promotions == []
    assert graph_repository.synced_dependency_rejections[0].reason == "unsupported_role"
