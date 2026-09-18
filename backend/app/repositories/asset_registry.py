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


class InMemoryAssetRegistry(AssetRegistry):
    """Temporary in-memory registry for resolved assets.

    The remaining equity seeds are development conveniences only. ETFs are
    deliberately not hardcoded: they must be resolved dynamically by a provider.
    """

    def __init__(self) -> None:
        seed = [
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
        self._assets = {asset.ticker: asset for asset in seed}

    def get(self, ticker: str) -> AssetResolution | None:
        return self._assets.get(ticker.upper())

    def save(self, asset: AssetResolution) -> AssetResolution:
        self._assets[asset.ticker.upper()] = asset
        return asset
