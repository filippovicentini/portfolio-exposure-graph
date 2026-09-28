from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from uuid import UUID

from app.domain.models import (
    CandidateEntityResolution,
    CandidateEntityResolutionTarget,
    CompanyFilingTarget,
    CompanyFilings,
    CompanyMetadata,
    CompanyMetadataTarget,
    CompanyResolution,
    DependencyPromotionRejection,
    DependencyPromotionTarget,
    EvidenceBackedDependency,
    EvidenceSemanticCandidateBatch,
    EvidenceSemanticTarget,
    EtfHolding,
    ExposurePath,
    FilingEvidenceBatch,
    FilingEvidenceTarget,
    Portfolio,
    StructuralExposureItem,
    SupplierIdentity,
)


class GraphRepository(ABC):
    """Persistence boundary for portfolio exposure graph data."""

    @abstractmethod
    def sync_portfolio(
        self,
        portfolio: Portfolio,
        etf_holdings: Mapping[str, list[EtfHolding]],
        company_resolutions: Mapping[str, CompanyResolution],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_exposure_paths(self, portfolio_id: UUID) -> list[ExposurePath]:
        raise NotImplementedError

    @abstractmethod
    def get_company_metadata_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[CompanyMetadataTarget]:
        raise NotImplementedError

    @abstractmethod
    def sync_company_metadata(
        self,
        company_metadata: Mapping[str, CompanyMetadata],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_company_filing_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[CompanyFilingTarget]:
        raise NotImplementedError

    @abstractmethod
    def sync_company_filings(
        self,
        company_filings: Mapping[str, CompanyFilings],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_filing_evidence_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[FilingEvidenceTarget]:
        raise NotImplementedError

    @abstractmethod
    def sync_filing_evidence(
        self,
        evidence_batches: Mapping[str, FilingEvidenceBatch],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_evidence_semantic_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[EvidenceSemanticTarget]:
        raise NotImplementedError

    @abstractmethod
    def sync_evidence_semantic_candidates(
        self,
        candidate_batches: Mapping[str, EvidenceSemanticCandidateBatch],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_candidate_entity_resolution_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[CandidateEntityResolutionTarget]:
        raise NotImplementedError

    @abstractmethod
    def get_supplier_by_alias(self, alias: str) -> SupplierIdentity | None:
        raise NotImplementedError

    @abstractmethod
    def sync_candidate_entity_resolutions(
        self,
        resolutions: list[CandidateEntityResolution],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_dependency_promotion_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[DependencyPromotionTarget]:
        raise NotImplementedError

    @abstractmethod
    def sync_evidence_backed_dependencies(
        self,
        promotions: list[EvidenceBackedDependency],
        rejections: list[DependencyPromotionRejection],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_industry_exposures(
        self,
        portfolio_id: UUID,
    ) -> list[StructuralExposureItem]:
        raise NotImplementedError

    @abstractmethod
    def get_country_exposures(
        self,
        portfolio_id: UUID,
    ) -> list[StructuralExposureItem]:
        raise NotImplementedError

    def close(self) -> None:
        """Release repository resources when needed."""
