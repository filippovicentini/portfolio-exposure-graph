from __future__ import annotations

import re
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from portfolio_exposure_graph.domain.enums import (
    AssetStatus,
    AssetType,
    CandidateRelationType,
    CandidateRole,
    EnrichmentJobStatus,
    PortfolioStatus,
    SupplierCompanyLinkStatus,
)


# US-listed ticker syntax: a letter, then letters, digits, "." or "-".
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,23}$")


class PositionInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)
    weight_pct: float = Field(gt=0, le=100)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized):
            raise ValueError(
                f"Invalid ticker {normalized!r}: expected a letter followed by "
                "letters, digits, '.' or '-'"
            )
        return normalized


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    positions: list[PositionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_positions(self) -> "PortfolioCreate":
        tickers = [position.ticker for position in self.positions]
        if len(set(tickers)) != len(tickers):
            raise ValueError("Duplicate tickers are not allowed")

        # Weights may sum to less than 100%: the remainder (e.g. bonds or cash
        # left out of the analysis) is reported as not analysed, so every
        # percentage stays a share of the real portfolio.
        total = sum(position.weight_pct for position in self.positions)
        if total > 100.0 + 0.01:
            raise ValueError(f"Portfolio weights must not exceed 100%; got {total:.2f}%")
        return self


class AssetResolution(BaseModel):
    asset_id: UUID = Field(default_factory=uuid4)
    ticker: str
    exchange: str | None = None
    asset_type: AssetType = AssetType.UNKNOWN
    status: AssetStatus
    company_name: str | None = None
    cik: str | None = None
    isin: str | None = None


class PortfolioPosition(BaseModel):
    ticker: str
    weight_pct: float
    asset: AssetResolution


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EnrichmentJob(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    ticker: str
    status: EnrichmentJobStatus = EnrichmentJobStatus.QUEUED
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    claimed_at: datetime | None = None
    # Earliest time a requeued job may be claimed again (retry backoff).
    next_attempt_at: datetime | None = None
    resolved_asset_type: AssetType | None = None


class EnrichmentProcessResult(BaseModel):
    jobs_claimed: int = Field(ge=0)
    jobs_completed: int = Field(ge=0)
    jobs_requeued: int = Field(ge=0)
    jobs_failed: int = Field(ge=0)
    portfolios_updated: int = Field(ge=0)
    jobs: list[EnrichmentJob] = Field(default_factory=list)


class Portfolio(BaseModel):
    portfolio_id: UUID = Field(default_factory=uuid4)
    name: str
    status: PortfolioStatus
    positions: list[PortfolioPosition]
    enrichment_jobs: list[EnrichmentJob] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EtfHolding(BaseModel):
    """One constituent of an ETF.

    ``ticker`` is the constituent's identifier within the look-through: its
    US ticker when it is US-listed, otherwise a listing-qualified ticker or
    its ISIN, so a local ticker never collides with an unrelated US one
    ("SU" in Paris is Schneider Electric, "SU" in New York is Suncor).
    """

    ticker: str = Field(min_length=1, max_length=64)
    description: str | None = None
    weight_pct: float = Field(ge=0, le=100)
    isin: str | None = None
    country: str | None = None
    sector: str | None = None
    asset_class: str | None = None
    exchange: str | None = None
    # True: resolvable to an SEC company by ticker. False: never resolve by
    # ticker. None: unknown (US-ETF data sources), resolved as before.
    us_listed: bool | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_holding_ticker(cls, value: str) -> str:
        return value.strip().upper()


class CompanyResolution(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)
    cik: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)
    exchange: str | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_company_ticker(cls, value: str) -> str:
        return value.strip().upper()


class CompanyMetadataTarget(BaseModel):
    cik: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)


class CompanyMetadata(BaseModel):
    cik: str = Field(min_length=1, max_length=10)
    industry_code: str | None = None
    industry_name: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    source_url: str = Field(min_length=1)


class ExposureBreakdown(BaseModel):
    ticker: str
    direct_weight_pct: float
    indirect_weight_pct: float
    total_weight_pct: float
    via_etfs: list[str] = Field(default_factory=list)
    name: str | None = None
    country: str | None = None
    sector: str | None = None
    asset_class: str | None = None


class ClassificationBucket(BaseModel):
    name: str
    weight_pct: float = Field(ge=0)


class PortfolioLookthrough(BaseModel):
    portfolio_id: UUID
    exposures: list[ExposureBreakdown]
    unexpanded_etfs: list[str] = Field(default_factory=list)
    # Sum of the position weights, and the part of the portfolio left out.
    analysed_weight_pct: float = 100.0
    not_analysed_weight_pct: float = 0.0
    # Look-through weight by the classification each ETF issuer publishes
    # for its holdings, plus direct equities. "Unclassified" collects weight
    # with no classification (e.g. direct equities, unexpanded ETFs).
    countries: list[ClassificationBucket] = Field(default_factory=list)
    sectors: list[ClassificationBucket] = Field(default_factory=list)
    asset_classes: list[ClassificationBucket] = Field(default_factory=list)
    classification_basis: str = (
        "Country, sector and asset class as published by each ETF issuer for "
        "its holdings (issuer-defined location and sector); weights are "
        "position weight x holding weight"
    )


class ExposurePath(BaseModel):
    asset_path: list[str] = Field(min_length=1)
    relations: list[str] = Field(min_length=1)
    effective_weight_pct: float = Field(ge=0)


class GraphSyncResult(BaseModel):
    portfolio_id: UUID
    assets_synced: int = Field(ge=0)
    companies_synced: int = Field(ge=0)
    ownership_edges_synced: int = Field(ge=0)
    holding_edges_synced: int = Field(ge=0)
    represents_edges_synced: int = Field(ge=0)
    unexpanded_etfs: list[str] = Field(default_factory=list)
    unresolved_company_assets: list[str] = Field(default_factory=list)


class PortfolioExposurePaths(BaseModel):
    portfolio_id: UUID
    paths: list[ExposurePath] = Field(default_factory=list)


class CompanyMetadataSyncResult(BaseModel):
    portfolio_id: UUID
    companies_requested: int = Field(ge=0)
    companies_enriched: int = Field(ge=0)
    industry_edges_synced: int = Field(ge=0)
    country_edges_synced: int = Field(ge=0)
    unresolved_company_ciks: list[str] = Field(default_factory=list)


class CompanyFilingTarget(BaseModel):
    cik: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)


class SecFiling(BaseModel):
    cik: str = Field(min_length=1, max_length=10)
    accession_number: str = Field(min_length=1)
    form: str = Field(pattern=r"^(10-K|10-Q)$")
    filing_date: date
    report_date: date | None = None
    primary_document: str | None = None
    source_url: str = Field(min_length=1)
    filing_index_url: str = Field(min_length=1)
    submissions_url: str = Field(min_length=1)


class CompanyFilings(BaseModel):
    cik: str = Field(min_length=1, max_length=10)
    source_url: str = Field(min_length=1)
    filings: list[SecFiling] = Field(default_factory=list)


class CompanyFilingsSyncResult(BaseModel):
    portfolio_id: UUID
    companies_requested: int = Field(ge=0)
    companies_synced: int = Field(ge=0)
    filings_synced: int = Field(ge=0)
    unresolved_company_ciks: list[str] = Field(default_factory=list)


class FilingEvidenceTarget(BaseModel):
    accession_number: str = Field(min_length=1)
    cik: str = Field(min_length=1, max_length=10)
    form: str = Field(pattern=r"^(10-K|10-Q)$")
    filing_date: date
    source_url: str = Field(min_length=1)


class FilingEvidence(BaseModel):
    evidence_id: str = Field(min_length=1)
    accession_number: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    matched_terms: list[str] = Field(default_factory=list)
    source_url: str = Field(min_length=1)
    source_date: date
    extraction_method: str = Field(min_length=1)


class FilingEvidenceBatch(BaseModel):
    accession_number: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    extraction_method: str = Field(min_length=1)
    evidence: list[FilingEvidence] = Field(default_factory=list)


class FilingEvidenceSyncResult(BaseModel):
    portfolio_id: UUID
    filings_requested: int = Field(ge=0)
    filings_processed: int = Field(ge=0)
    filings_with_evidence: int = Field(ge=0)
    evidence_synced: int = Field(ge=0)
    filings_without_evidence: list[str] = Field(default_factory=list)
    unresolved_filing_accessions: list[str] = Field(default_factory=list)


class EvidenceSemanticTarget(BaseModel):
    evidence_id: str = Field(min_length=1)
    subject_cik: str = Field(min_length=1, max_length=10)
    subject_name: str = Field(min_length=1)
    accession_number: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_date: date


class RelationshipCandidate(BaseModel):
    candidate_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    subject_cik: str = Field(min_length=1, max_length=10)
    subject_name: str = Field(min_length=1)
    object_mention: str = Field(min_length=1)
    proposed_relation: CandidateRelationType = CandidateRelationType.DEPENDS_ON
    role: CandidateRole
    supporting_text: str = Field(min_length=1)
    extraction_method: str = Field(min_length=1)
    model_name: str = Field(min_length=1)


class EvidenceSemanticCandidateBatch(BaseModel):
    evidence_id: str = Field(min_length=1)
    extraction_method: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    candidates: list[RelationshipCandidate] = Field(default_factory=list)


class EvidenceSemanticCandidatesSyncResult(BaseModel):
    portfolio_id: UUID
    evidence_requested: int = Field(ge=0)
    evidence_processed: int = Field(ge=0)
    evidence_with_candidates: int = Field(ge=0)
    candidates_synced: int = Field(ge=0)
    evidence_without_candidates: list[str] = Field(default_factory=list)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)


class CandidateEntityResolutionTarget(BaseModel):
    candidate_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    subject_cik: str = Field(min_length=1, max_length=10)
    subject_name: str = Field(min_length=1)
    object_mention: str = Field(min_length=1)
    role: CandidateRole
    supporting_text: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)


class SupplierIdentity(BaseModel):
    supplier_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    aliases: list[str] = Field(min_length=1)

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: list[str]) -> list[str]:
        aliases: list[str] = []
        seen: set[str] = set()
        for alias in value:
            cleaned = alias.strip()
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            aliases.append(cleaned)
        if not aliases:
            raise ValueError("Supplier aliases cannot be empty")
        return aliases


class SupplierCompanyLink(BaseModel):
    """Outcome of matching an internal Supplier to an SEC-registered Company."""

    supplier_id: str = Field(min_length=1)
    status: SupplierCompanyLinkStatus
    method: str = Field(min_length=1)
    company_cik: str | None = Field(default=None, max_length=10)
    company_name: str | None = None
    matched_name: str | None = None
    candidate_ciks: list[str] = Field(default_factory=list)
    source_url: str | None = None


class SupplierCompanyLinkSyncResult(BaseModel):
    portfolio_id: UUID
    suppliers_requested: int = Field(ge=0)
    suppliers_linked: int = Field(ge=0)
    linked_supplier_ids: list[str] = Field(default_factory=list)
    ambiguous_supplier_ids: list[str] = Field(default_factory=list)
    unmatched_supplier_ids: list[str] = Field(default_factory=list)
    directory_unavailable: bool = False


class CandidateEntityResolution(BaseModel):
    candidate_id: str = Field(min_length=1)
    supplier: SupplierIdentity
    resolution_method: str = Field(min_length=1)


class CandidateEntityResolutionSyncResult(BaseModel):
    portfolio_id: UUID
    candidates_requested: int = Field(ge=0)
    candidates_resolved: int = Field(ge=0)
    suppliers_synced: int = Field(ge=0)
    unresolved_candidate_ids: list[str] = Field(default_factory=list)


class DependencyPromotionTarget(BaseModel):
    candidate_id: str = Field(min_length=1)
    subject_cik: str = Field(min_length=1, max_length=10)
    subject_name: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    supplier_canonical_name: str = Field(min_length=1)
    supplier_aliases: list[str] = Field(min_length=1)
    object_mention: str = Field(min_length=1)
    proposed_relation: CandidateRelationType
    role: CandidateRole
    supporting_text: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    accession_number: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_date: date
    extraction_method: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    entity_resolution_method: str = Field(min_length=1)


class EvidenceBackedDependency(BaseModel):
    candidate_id: str = Field(min_length=1)
    subject_cik: str = Field(min_length=1, max_length=10)
    supplier_id: str = Field(min_length=1)
    role: CandidateRole
    evidence_id: str = Field(min_length=1)
    accession_number: str = Field(min_length=1)
    promotion_method: str = Field(min_length=1)


class DependencyPromotionRejection(BaseModel):
    candidate_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    promotion_method: str = Field(min_length=1)


class EvidenceBackedDependenciesSyncResult(BaseModel):
    portfolio_id: UUID
    candidates_requested: int = Field(ge=0)
    candidates_promoted: int = Field(ge=0)
    dependency_edges_synced: int = Field(ge=0)
    candidates_rejected: int = Field(ge=0)
    rejected_candidate_ids: list[str] = Field(default_factory=list)
    unresolved_candidate_ids: list[str] = Field(default_factory=list)


class DependencyProvenance(BaseModel):
    candidate_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    accession_number: str = Field(min_length=1)
    object_mention: str = Field(min_length=1)
    role: CandidateRole
    supporting_text: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_date: date
    extraction_method: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    entity_resolution_method: str = Field(min_length=1)


class DependencyPath(BaseModel):
    asset_path: list[str] = Field(min_length=1)
    relations: list[str] = Field(min_length=1)
    company_cik: str = Field(min_length=1, max_length=10)
    company_name: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    supplier_name: str = Field(min_length=1)
    roles: list[CandidateRole] = Field(min_length=1)
    company_path_weight_pct: float = Field(ge=0)
    basis: str = Field(min_length=1)
    promotion_method: str = Field(min_length=1)
    provenance: list[DependencyProvenance] = Field(min_length=1)


class PortfolioDependencyPaths(BaseModel):
    portfolio_id: UUID
    paths: list[DependencyPath] = Field(default_factory=list)
    weight_basis: str = (
        "Sourced OWNS / one-level OWNS * HOLDS weight reaching the dependent company"
    )
    dependency_basis: str = (
        "Qualitative evidence-backed DEPENDS_ON; no numeric supplier impact is inferred"
    )


class DependencyExposureRow(BaseModel):
    """One holding route reaching one company that depends on one supplier.

    Only promoted DEPENDS_ON edges with verifiable provenance are included,
    the same set the dependency-path API returns.
    """

    asset_path: list[str] = Field(min_length=1)
    company_cik: str = Field(min_length=1, max_length=10)
    company_name: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    supplier_name: str = Field(min_length=1)
    roles: list[CandidateRole] = Field(min_length=1)
    company_path_weight_pct: float = Field(ge=0)
    # The supplier's own SEC company, when an IDENTIFIED_AS link exists.
    supplier_company_cik: str | None = Field(default=None, max_length=10)
    supplier_company_name: str | None = None


class DependentCompanyExposure(BaseModel):
    company_cik: str = Field(min_length=1, max_length=10)
    company_name: str = Field(min_length=1)
    weight_pct: float = Field(ge=0)


class SupplierExposureItem(BaseModel):
    supplier_id: str = Field(min_length=1)
    supplier_name: str = Field(min_length=1)
    weight_pct: float = Field(ge=0)
    roles: list[CandidateRole] = Field(min_length=1)
    companies: list[DependentCompanyExposure] = Field(min_length=1)
    supplier_company_cik: str | None = Field(default=None, max_length=10)
    supplier_company_name: str | None = None
    # Portfolio weight already held in the supplier itself (direct + one-level
    # look-through). None when the supplier is not linked to an SEC company.
    held_weight_pct: float | None = Field(default=None, ge=0)


class RoleExposureItem(BaseModel):
    role: CandidateRole
    weight_pct: float = Field(ge=0)
    supplier_count: int = Field(ge=1)


class PortfolioSupplierExposure(BaseModel):
    portfolio_id: UUID
    suppliers: list[SupplierExposureItem] = Field(default_factory=list)
    roles: list[RoleExposureItem] = Field(default_factory=list)
    dependency_coverage_pct: float = Field(ge=0)
    weight_basis: str = (
        "Sourced portfolio / one-level look-through weight reaching companies that "
        "depend on the supplier (or on a supplier in the role); each holding route "
        "to a company is counted once per supplier or role"
    )
    dependency_basis: str = (
        "Qualitative evidence-backed DEPENDS_ON; no numeric supplier impact is inferred"
    )
    held_basis: str = (
        "Held weight is the sourced portfolio / one-level look-through weight "
        "already held in the supplier's own SEC-registered company; it is only "
        "reported for suppliers linked to an SEC registrant"
    )
    overlap_basis: str = (
        "A company usually depends on several suppliers, so supplier and role "
        "weights overlap and can sum to more than 100%; the dependency coverage "
        "figure counts each holding route once"
    )


class StructuralExposureItem(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    weight_pct: float = Field(ge=0)


class PortfolioStructuralExposure(BaseModel):
    portfolio_id: UUID
    industries: list[StructuralExposureItem] = Field(default_factory=list)
    countries: list[StructuralExposureItem] = Field(default_factory=list)
    industry_coverage_pct: float = Field(ge=0)
    country_coverage_pct: float = Field(ge=0)
    industry_basis: str = "SEC primary SIC"
    country_basis: str = "SEC business address"
