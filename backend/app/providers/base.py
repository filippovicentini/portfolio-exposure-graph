from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import AssetResolution, CompanyMetadata, EtfHolding


class AssetDataProvider(ABC):
    """Resolve an asset ticker using an external data source."""

    @abstractmethod
    def resolve(self, ticker: str) -> AssetResolution | None:
        raise NotImplementedError


class EtfHoldingsProvider(ABC):
    """Return the latest known holdings for an ETF ticker."""

    @abstractmethod
    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        raise NotImplementedError


class CompanyMetadataProvider(ABC):
    """Return structural company metadata from an external data source."""

    @abstractmethod
    def get_metadata(self, cik: str) -> CompanyMetadata | None:
        raise NotImplementedError
