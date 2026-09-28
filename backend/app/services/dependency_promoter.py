from __future__ import annotations

from app.domain.enums import CandidateRelationType, CandidateRole
from app.domain.models import DependencyPromotionTarget, EvidenceBackedDependency
from app.services.candidate_entity_resolver import DeterministicCandidateEntityResolver


class DependencyPromotionRejected(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DeterministicDependencyPromoter:
    """Promote only fully resolved, source-verifiable dependency candidates."""

    PROMOTION_METHOD = "resolved_evidence_candidate_v1"
    PROMOTABLE_ROLES = {
        CandidateRole.FOUNDRY,
        CandidateRole.MEMORY_SUPPLIER,
        CandidateRole.CONTRACT_MANUFACTURER,
        CandidateRole.MANUFACTURING_PARTNER,
        CandidateRole.COMPONENT_SUPPLIER,
        CandidateRole.SUPPLIER,
    }

    def promote(self, target: DependencyPromotionTarget) -> EvidenceBackedDependency:
        if target.proposed_relation != CandidateRelationType.DEPENDS_ON:
            raise DependencyPromotionRejected("unsupported_relation")
        if target.role not in self.PROMOTABLE_ROLES:
            raise DependencyPromotionRejected("unsupported_role")
        if not self._contains_span(target.supporting_text, target.object_mention):
            raise DependencyPromotionRejected("object_mention_not_in_supporting_text")
        if not self._contains_span(target.evidence_text, target.supporting_text):
            raise DependencyPromotionRejected("supporting_text_not_in_evidence")

        normalized_mention = DeterministicCandidateEntityResolver.normalize_alias(
            target.object_mention
        )
        normalized_aliases = {
            DeterministicCandidateEntityResolver.normalize_alias(alias)
            for alias in target.supplier_aliases
        }
        if normalized_mention not in normalized_aliases:
            raise DependencyPromotionRejected("object_mention_not_supplier_alias")

        return EvidenceBackedDependency(
            candidate_id=target.candidate_id,
            subject_cik=target.subject_cik,
            supplier_id=target.supplier_id,
            role=target.role,
            evidence_id=target.evidence_id,
            accession_number=target.accession_number,
            promotion_method=self.PROMOTION_METHOD,
        )

    @staticmethod
    def _contains_span(source: str, span: str) -> bool:
        return span.strip().casefold() in source.casefold()
