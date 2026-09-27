from __future__ import annotations

import json
from datetime import date

import httpx

from app.domain.enums import CandidateRole
from app.domain.models import EvidenceSemanticTarget
from app.providers.ollama_semantic_candidate_provider import (
    OllamaSemanticCandidateProvider,
)


def make_target(
    evidence_text: str = (
        "We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, "
        "or TSMC, and Samsung Electronics Co., Ltd. to produce our wafers."
    ),
) -> EvidenceSemanticTarget:
    return EvidenceSemanticTarget(
        evidence_id="0001045810-26-000001:abc123",
        subject_cik="0001045810",
        subject_name="NVIDIA CORP",
        accession_number="0001045810-26-000001",
        evidence_text=evidence_text,
        source_url="https://example.com/filing.htm",
        source_date=date(2026, 2, 25),
    )


def test_ollama_semantic_provider_uses_structured_output_and_filters_hallucinations():
    requests: list[dict] = []
    supporting_text = (
        "We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, "
        "or TSMC, and Samsung Electronics Co., Ltd. to produce our wafers."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "candidates": [
                                {
                                    "object_mention": "TSMC",
                                    "role": "foundry",
                                    "supporting_text": supporting_text,
                                },
                                {
                                    "object_mention": "Intel",
                                    "role": "foundry",
                                    "supporting_text": supporting_text,
                                },
                                {
                                    "object_mention": "tsmc",
                                    "role": "foundry",
                                    "supporting_text": supporting_text,
                                },
                            ]
                        }
                    ),
                }
            },
        )

    provider = OllamaSemanticCandidateProvider(
        base_url="http://ollama.test",
        model_name="qwen3:4b-instruct",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    first = provider.extract_candidates(make_target(), limit=5)
    second = provider.extract_candidates(make_target(), limit=5)

    assert first is not None
    assert second is not None
    assert len(first.candidates) == 1
    assert first.candidates[0].object_mention == "TSMC"
    assert first.candidates[0].role == CandidateRole.FOUNDRY
    assert first.candidates[0].supporting_text == supporting_text
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id
    assert first.extraction_method == "ollama_structured_dependency_v1"
    assert first.model_name == "qwen3:4b-instruct"

    assert len(requests) == 2
    payload = requests[0]
    assert payload["model"] == "qwen3:4b-instruct"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0}
    assert payload["format"]["type"] == "object"
    assert "candidates" in payload["format"]["properties"]
    assert "NVIDIA CORP" in payload["messages"][1]["content"]


def test_ollama_semantic_provider_rejects_non_verbatim_and_subject_mentions():
    evidence_text = (
        "NVIDIA CORP works with TSMC for wafer fabrication. "
        "The company also discusses manufacturing capacity."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "candidates": [
                                {
                                    "object_mention": "NVIDIA",
                                    "role": "supplier",
                                    "supporting_text": "NVIDIA CORP works with TSMC for wafer fabrication.",
                                },
                                {
                                    "object_mention": "TSMC",
                                    "role": "foundry",
                                    "supporting_text": "TSMC manufactures wafers for NVIDIA.",
                                },
                            ]
                        }
                    ),
                }
            },
        )

    provider = OllamaSemanticCandidateProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    batch = provider.extract_candidates(make_target(evidence_text), limit=5)

    assert batch is not None
    assert batch.candidates == []


def test_ollama_semantic_provider_accepts_empty_candidate_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": '{"candidates": []}',
                }
            },
        )

    provider = OllamaSemanticCandidateProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    batch = provider.extract_candidates(make_target(), limit=5)

    assert batch is not None
    assert batch.candidates == []


def test_ollama_semantic_provider_requires_positive_limit():
    provider = OllamaSemanticCandidateProvider()

    try:
        provider.extract_candidates(make_target(), limit=0)
    except ValueError as exc:
        assert str(exc) == "limit must be at least 1"
    else:
        raise AssertionError("expected ValueError")
