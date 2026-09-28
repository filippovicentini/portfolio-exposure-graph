from __future__ import annotations

from app.domain.enums import CandidateRole
from app.domain.models import CandidateEntityResolutionTarget
from app.services.candidate_entity_resolver import DeterministicCandidateEntityResolver


EVIDENCE = (
    "We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, "
    "or TSMC, and Samsung Electronics Co., Ltd., or Samsung, to produce our semiconductor "
    "wafers. We purchase memory from SK Hynix Inc., Micron Technology, Inc., and Samsung."
)


def make_target(object_mention: str, role: CandidateRole) -> CandidateEntityResolutionTarget:
    return CandidateEntityResolutionTarget(
        candidate_id=f"candidate:{object_mention}",
        evidence_id="evidence-1",
        subject_cik="0001045810",
        subject_name="NVIDIA CORP",
        object_mention=object_mention,
        role=role,
        supporting_text=EVIDENCE,
        evidence_text=EVIDENCE,
    )


def test_resolver_extracts_forward_alias_from_evidence():
    resolver = DeterministicCandidateEntityResolver()

    supplier = resolver.resolve(
        make_target(
            "Taiwan Semiconductor Manufacturing Company Limited",
            CandidateRole.FOUNDRY,
        )
    )

    assert supplier.canonical_name == "Taiwan Semiconductor Manufacturing Company Limited"
    assert supplier.aliases == [
        "Taiwan Semiconductor Manufacturing Company Limited",
        "TSMC",
    ]
    assert supplier.supplier_id.startswith("supplier:")


def test_resolver_maps_backward_alias_to_same_supplier_identity():
    resolver = DeterministicCandidateEntityResolver()

    long_form = resolver.resolve(
        make_target("Samsung Electronics Co., Ltd.", CandidateRole.FOUNDRY)
    )
    short_form = resolver.resolve(
        make_target("Samsung", CandidateRole.MEMORY_SUPPLIER)
    )

    assert long_form.canonical_name == "Samsung Electronics Co., Ltd."
    assert short_form.canonical_name == "Samsung Electronics Co., Ltd."
    assert long_form.supplier_id == short_form.supplier_id
    assert short_form.aliases == ["Samsung Electronics Co., Ltd.", "Samsung"]


def test_resolver_uses_exact_mention_when_no_alias_is_explicit():
    resolver = DeterministicCandidateEntityResolver()

    supplier = resolver.resolve(
        make_target("Micron Technology, Inc.", CandidateRole.MEMORY_SUPPLIER)
    )

    assert supplier.canonical_name == "Micron Technology, Inc."
    assert supplier.aliases == ["Micron Technology, Inc."]


def test_resolver_does_not_merge_different_corporate_suffixes():
    resolver = DeterministicCandidateEntityResolver()
    first = make_target("Example Inc.", CandidateRole.SUPPLIER)
    first.evidence_text = "We purchase components from Example Inc."
    second = make_target("Example Corp.", CandidateRole.SUPPLIER)
    second.evidence_text = "We purchase components from Example Corp."

    first_supplier = resolver.resolve(first)
    second_supplier = resolver.resolve(second)

    assert first_supplier.supplier_id != second_supplier.supplier_id
