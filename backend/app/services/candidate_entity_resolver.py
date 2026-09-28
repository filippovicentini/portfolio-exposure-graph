from __future__ import annotations

import re

from app.domain.entity_identity import normalize_entity_name, stable_supplier_id
from app.domain.models import CandidateEntityResolutionTarget, SupplierIdentity


class DeterministicCandidateEntityResolver:
    """Resolve exact candidate mentions into conservative internal Supplier identities."""

    RESOLUTION_METHOD = "evidence_alias_exact_v1"

    def resolve(self, target: CandidateEntityResolutionTarget) -> SupplierIdentity:
        mention = target.object_mention.strip()
        canonical_name = mention
        aliases = [mention]

        forward_alias = self._forward_alias(target.evidence_text, mention)
        if forward_alias is not None:
            aliases.append(forward_alias)
        else:
            backward_canonical = self._backward_canonical(
                target.evidence_text,
                mention,
            )
            if backward_canonical is not None:
                canonical_name = backward_canonical
                aliases.insert(0, backward_canonical)

        aliases = self._dedupe_aliases(aliases)
        return SupplierIdentity(
            supplier_id=stable_supplier_id(canonical_name),
            canonical_name=canonical_name,
            aliases=aliases,
        )

    @staticmethod
    def normalize_alias(value: str) -> str:
        return normalize_entity_name(value)

    @staticmethod
    def _forward_alias(source: str, mention: str) -> str | None:
        pattern = re.compile(
            rf"{re.escape(mention)}\s*,\s*or\s+([^,;.\n]{{1,80}}?)(?=\s*[,;.])",
            flags=re.IGNORECASE,
        )
        match = pattern.search(source)
        if match is None:
            return None
        alias = match.group(1).strip()
        return alias or None

    @classmethod
    def _backward_canonical(cls, source: str, mention: str) -> str | None:
        marker = re.compile(
            rf",\s*or\s+{re.escape(mention)}\s*(?=[,;.])",
            flags=re.IGNORECASE,
        ).search(source)
        if marker is None:
            return None

        prefix = source[: marker.start()].rstrip()
        sentence_start = prefix.rfind(". ")
        if sentence_start >= 0:
            prefix = prefix[sentence_start + 2 :]

        lower_prefix = prefix.casefold()
        cut_points: list[int] = []
        for delimiter in (", and ", " and ", "such as ", "including ", "namely "):
            index = lower_prefix.rfind(delimiter)
            if index >= 0:
                cut_points.append(index + len(delimiter))
        if cut_points:
            prefix = prefix[max(cut_points) :]

        canonical = prefix.strip(" \t\n,;:-")
        if not canonical:
            return None
        if cls.normalize_alias(canonical) == cls.normalize_alias(mention):
            return None
        return canonical

    @classmethod
    def _dedupe_aliases(cls, aliases: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            cleaned = alias.strip()
            normalized = cls.normalize_alias(cleaned)
            if not cleaned or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(cleaned)
        return result
