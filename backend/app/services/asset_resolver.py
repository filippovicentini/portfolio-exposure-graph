from __future__ import annotations

import logging

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import TICKER_PATTERN, AssetResolution
from app.providers.base import AssetDataProvider
from app.repositories.asset_registry import AssetRegistry

logger = logging.getLogger(__name__)


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

        resolved, _errors = self._query_providers(normalized)
        if resolved:
            return self.registry.save(resolved)

        pending = AssetResolution(
            ticker=normalized,
            status=AssetStatus.PENDING_ENRICHMENT,
            asset_type=AssetType.UNKNOWN,
        )
        return self.registry.save(pending)

    def enrich(self, ticker: str) -> tuple[AssetResolution | None, list[str]]:
        """Retry the providers for a ticker, bypassing any cached pending entry.

        Returns the resolution (also saved to the registry) or ``None``, plus
        the provider errors encountered. ``None`` with no errors means every
        provider answered and none recognised the ticker.
        """
        normalized = ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized):
            return None, [f"Invalid ticker {normalized!r}"]

        existing = self.registry.get(normalized)
        if existing and existing.status == AssetStatus.READY:
            return existing, []

        if not self.providers:
            return None, ["No asset providers are configured"]

        resolved, errors = self._query_providers(normalized)
        if resolved:
            return self.registry.save(resolved), errors
        return None, errors

    def mark_unsupported(self, ticker: str) -> AssetResolution:
        normalized = ticker.strip().upper()
        return self.registry.save(
            AssetResolution(
                ticker=normalized,
                status=AssetStatus.UNSUPPORTED,
                asset_type=AssetType.UNKNOWN,
            )
        )

    def _query_providers(
        self, ticker: str
    ) -> tuple[AssetResolution | None, list[str]]:
        errors: list[str] = []
        for provider in self.providers:
            name = provider.__class__.__name__
            try:
                resolved = provider.resolve(ticker)
            except Exception as exc:
                logger.exception(
                    "Asset provider %s failed for ticker %s", name, ticker
                )
                errors.append(f"{name}: {exc}")
                continue

            if resolved:
                return resolved, errors
        return None, errors
