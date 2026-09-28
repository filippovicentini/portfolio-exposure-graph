from datetime import date

import pytest

from app.domain.enums import CandidateRelationType, CandidateRole
from app.domain.models import DependencyPromotionTarget
from app.services.dependency_promoter import (
    DependencyPromotionRejected,
    DeterministicDependencyPromoter,
)


def make_target(**overrides) -> DependencyPromotionTarget:
    evidence_text = (
        "We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, "
        "or TSMC, to produce our semiconductor wafers."
    )
    values = dict(
        candidate_id="candidate-tsmc",
        subject_cik="0001045810",
        subject_name="NVIDIA CORP",
        supplier_id="supplier:tsmc",
        supplier_canonical_name="Taiwan Semiconductor Manufacturing Company Limited",
        supplier_aliases=["Taiwan Semiconductor Manufacturing Company Limited", "TSMC"],
        object_mention="TSMC",
        proposed_relation=CandidateRelationType.DEPENDS_ON,
        role=CandidateRole.FOUNDRY,
        supporting_text=evidence_text,
        evidence_id="evidence-1",
        evidence_text=evidence_text,
        accession_number="0001045810-26-000001",
        source_url="https://example.com/filing.htm",
        source_date=date(2026, 2, 25),
        extraction_method="ollama_structured_dependency_v1",
        model_name="qwen3:4b-instruct",
        entity_resolution_method="evidence_alias_exact_v1",
    )
    values.update(overrides)
    return DependencyPromotionTarget(**values)


def test_dependency_promoter_accepts_resolved_verbatim_candidate():
    promoter = DeterministicDependencyPromoter()

    dependency = promoter.promote(make_target())

    assert dependency.candidate_id == "candidate-tsmc"
    assert dependency.subject_cik == "0001045810"
    assert dependency.supplier_id == "supplier:tsmc"
    assert dependency.role == CandidateRole.FOUNDRY
    assert dependency.promotion_method == "resolved_evidence_candidate_v1"


def test_dependency_promoter_rejects_other_role():
    promoter = DeterministicDependencyPromoter()

    with pytest.raises(DependencyPromotionRejected) as exc_info:
        promoter.promote(make_target(role=CandidateRole.OTHER))

    assert exc_info.value.reason == "unsupported_role"


def test_dependency_promoter_rejects_non_verbatim_supporting_text():
    promoter = DeterministicDependencyPromoter()

    with pytest.raises(DependencyPromotionRejected) as exc_info:
        promoter.promote(
            make_target(supporting_text="TSMC manufactures wafers for NVIDIA.")
        )

    assert exc_info.value.reason == "supporting_text_not_in_evidence"


def test_dependency_promoter_requires_object_mention_to_match_supplier_alias():
    promoter = DeterministicDependencyPromoter()

    with pytest.raises(DependencyPromotionRejected) as exc_info:
        promoter.promote(make_target(supplier_aliases=["Different Supplier"]))

    assert exc_info.value.reason == "object_mention_not_supplier_alias"
