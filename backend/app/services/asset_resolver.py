from __future__ import annotations

import logging
import re

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution
from app.providers.base import AssetDataProvider
from app.repositories.asset_registry import AssetRegistry

logger = logging.getLogger(__name__)

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,23}$")


class AssetResolver:
    def __init__(
        self,
        registry: AssetRegistry,
        providers: list[AssetDataProvider] | None = None,
    ) -> None:
        self.registry = registry
        self.providers = providers or []

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

        for provider in self.providers:
            try:
                resolved = provider.resolve(normalized)
            except Exception:
                logger.exception(
                    "Asset provider %s failed for ticker %s",
                    provider.__class__.__name__,
                    normalized,
                )
                continue

            if resolved:
                return self.registry.save(resolved)

        pending = AssetResolution(
            ticker=normalized,
            status=AssetStatus.PENDING_ENRICHMENT,
            asset_type=AssetType.UNKNOWN,
        )
        return self.registry.save(pending)
