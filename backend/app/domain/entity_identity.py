from __future__ import annotations

import hashlib
import re


def normalize_entity_name(value: str) -> str:
    """Normalize an entity label conservatively for stable internal identity."""
    tokens = re.findall(r"[\w&]+", value.casefold(), flags=re.UNICODE)
    return " ".join(tokens)


def stable_supplier_id(canonical_name: str) -> str:
    normalized = normalize_entity_name(canonical_name)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"supplier:{digest}"
