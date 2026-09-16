from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import AssetResolution


class AssetDataProvider(ABC):
    """Resolve an asset ticker using an external data source."""

    @abstractmethod
    def resolve(self, ticker: str) -> AssetResolution | None:
        raise NotImplementedError
