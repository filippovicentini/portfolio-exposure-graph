from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution


class AssetRegistry(ABC):
    @abstractmethod
    def get(self, ticker: str) -> AssetResolution | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, asset: AssetResolution) -> AssetResolution:
        raise NotImplementedError


def default_seed_assets() -> list[AssetResolution]:
    """Development-convenience equity seeds.

    They let the app resolve a couple of well-known equities without provider
    credentials. ETFs are deliberately not seeded: they must be resolved
    dynamically by a provider.
    """
    return [
        AssetResolution(
            ticker="NVDA",
            exchange="NASDAQ",
            asset_type=AssetType.EQUITY,
            status=AssetStatus.READY,
            company_name="NVIDIA Corporation",
        ),
        AssetResolution(
            ticker="MSFT",
            exchange="NASDAQ",
            asset_type=AssetType.EQUITY,
            status=AssetStatus.READY,
            company_name="Microsoft Corporation",
        ),
    ]


class InMemoryAssetRegistry(AssetRegistry):
    """In-memory registry for resolved assets, starting from the dev seeds."""

    def __init__(self) -> None:
        self._assets = {asset.ticker: asset for asset in default_seed_assets()}

    def get(self, ticker: str) -> AssetResolution | None:
        return self._assets.get(ticker.upper())

    def save(self, asset: AssetResolution) -> AssetResolution:
        self._assets[asset.ticker.upper()] = asset
        return asset
