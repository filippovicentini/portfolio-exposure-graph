from __future__ import annotations

import hashlib
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import CandidateRelationType, CandidateRole
from app.domain.models import (
    EvidenceSemanticCandidateBatch,
    EvidenceSemanticTarget,
    RelationshipCandidate,
)
from app.providers.base import EvidenceSemanticCandidateProvider


class _ExtractedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_mention: str = Field(min_length=1)
    role: CandidateRole
    supporting_text: str = Field(min_length=1)


class _ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[_ExtractedCandidate] = Field(default_factory=list)


class OllamaSemanticCandidateProvider(EvidenceSemanticCandidateProvider):
    """Extract conservative relationship candidates with a local Ollama model."""

    EXTRACTION_METHOD = "ollama_structured_dependency_v1"
    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_MODEL = "qwen3:4b-instruct"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model_name: str = DEFAULT_MODEL,
        client: httpx.Client | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name.strip() or self.DEFAULT_MODEL
        self.client = client or httpx.Client()
        self.timeout_seconds = max(1.0, timeout_seconds)

    def extract_candidates(
        self,
        evidence: EvidenceSemanticTarget,
        limit: int,
    ) -> EvidenceSemanticCandidateBatch | None:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        response = self.client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model_name,
                "stream": False,
                "format": _ExtractionResponse.model_json_schema(),
                "options": {"temperature": 0},
                "messages": [
                    {
                        "role": "system",
                        "content": self._system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": self._user_prompt(evidence, limit),
                    },
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            return None

        parsed = _ExtractionResponse.model_validate_json(content)
        candidates = self._validated_candidates(evidence, parsed, limit)
        return EvidenceSemanticCandidateBatch(
            evidence_id=evidence.evidence_id,
            extraction_method=self.EXTRACTION_METHOD,
            model_name=self.model_name,
            candidates=candidates,
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You extract explicit upstream supply, manufacturing, and production dependencies "
            "from SEC filing evidence. Return JSON that matches the provided schema. "
            "Be conservative: extract an organization only when the evidence explicitly describes "
            "it as an upstream supplier, foundry, manufacturer, manufacturing partner, memory "
            "supplier, or component supplier of the subject company. Do not infer competitors, "
            "customers, ecosystem participants, alternatives, or organizations mentioned only in "
            "hypothetical/risk language as dependencies. Do not extract the subject company itself. "
            "object_mention and supporting_text must be copied verbatim from the evidence."
        )

    @staticmethod
    def _user_prompt(evidence: EvidenceSemanticTarget, limit: int) -> str:
        roles = ", ".join(role.value for role in CandidateRole)
        return (
            f"Subject company: {evidence.subject_name}\n"
            f"Subject CIK: {evidence.subject_cik}\n"
            f"Allowed roles: {roles}\n"
            f"Return at most {limit} candidates.\n\n"
            "Evidence:\n"
            f"{evidence.evidence_text}\n\n"
            "Return JSON only. Use an empty candidates list when no explicit upstream dependency "
            "is supported by this evidence."
        )

    def _validated_candidates(
        self,
        evidence: EvidenceSemanticTarget,
        parsed: _ExtractionResponse,
        limit: int,
    ) -> list[RelationshipCandidate]:
        validated: list[RelationshipCandidate] = []
        seen: set[tuple[str, CandidateRole]] = set()

        for extracted in parsed.candidates:
            object_mention = self._source_span(
                evidence.evidence_text,
                extracted.object_mention,
            )
            supporting_text = self._source_span(
                evidence.evidence_text,
                extracted.supporting_text,
            )
            if object_mention is None or supporting_text is None:
                continue
            if object_mention.casefold() not in supporting_text.casefold():
                continue
            if self._is_subject_mention(object_mention, evidence.subject_name):
                continue

            dedupe_key = (object_mention.casefold(), extracted.role)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            candidate_id = self._candidate_id(
                evidence_id=evidence.evidence_id,
                object_mention=object_mention,
                role=extracted.role,
            )
            validated.append(
                RelationshipCandidate(
                    candidate_id=candidate_id,
                    evidence_id=evidence.evidence_id,
                    subject_cik=evidence.subject_cik,
                    subject_name=evidence.subject_name,
                    object_mention=object_mention,
                    proposed_relation=CandidateRelationType.DEPENDS_ON,
                    role=extracted.role,
                    supporting_text=supporting_text,
                    extraction_method=self.EXTRACTION_METHOD,
                    model_name=self.model_name,
                )
            )
            if len(validated) >= limit:
                break

        return validated

    @staticmethod
    def _source_span(source: str, proposed: str) -> str | None:
        needle = proposed.strip()
        if not needle:
            return None
        match = re.search(re.escape(needle), source, flags=re.IGNORECASE)
        if match is None:
            return None
        return source[match.start() : match.end()]

    @staticmethod
    def _is_subject_mention(mention: str, subject_name: str) -> bool:
        def normalize(value: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

        normalized_mention = normalize(mention)
        normalized_subject = normalize(subject_name)
        if not normalized_mention or not normalized_subject:
            return False
        if normalized_mention == normalized_subject:
            return True

        subject_tokens = normalized_subject.split()
        suffixes = {
            "corp",
            "corporation",
            "inc",
            "incorporated",
            "ltd",
            "limited",
            "plc",
            "company",
            "co",
        }
        while subject_tokens and subject_tokens[-1] in suffixes:
            subject_tokens.pop()
        return bool(subject_tokens) and normalized_mention == " ".join(subject_tokens)

    @staticmethod
    def _candidate_id(
        evidence_id: str,
        object_mention: str,
        role: CandidateRole,
    ) -> str:
        digest = hashlib.sha256(
            f"{evidence_id}\n{object_mention.casefold()}\n{role.value}".encode("utf-8")
        ).hexdigest()[:24]
        return f"{evidence_id}:{digest}"
