from __future__ import annotations

import re

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution
from app.repositories.asset_registry import AssetRegistry


TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,23}$")


class AssetResolver:
    def __init__(self, registry: AssetRegistry) -> None:
        self.registry = registry

    def resolve(self, ticker: str) -> AssetResolution:
        normalized = ticker.strip().upper()

        if not TICKER_PATTERN.fullmatch(normalized):
            return AssetResolution(
                ticker=normalized,
                status=AssetStatus.INVALID,
                asset_type=AssetType.UNKNOWN,
            )

        existing = self.registry.get(normalized)
        if existing:
            return existing

        pending = AssetResolution(
            ticker=normalized,
            status=AssetStatus.PENDING_ENRICHMENT,
            asset_type=AssetType.UNKNOWN,
        )
        return self.registry.save(pending)
