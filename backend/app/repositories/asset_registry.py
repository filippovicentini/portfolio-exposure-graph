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
    """Temporary registry for the first vertical slice.

    It deliberately contains only a tiny seed universe. A syntactically valid
    ticker missing from this registry is not treated as an error: the service
    creates a PENDING_ENRICHMENT asset so a future provider can resolve it.
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
            AssetResolution(
                ticker="QQQ",
                exchange="NASDAQ",
                asset_type=AssetType.ETF,
                status=AssetStatus.READY,
                company_name="Invesco QQQ Trust",
            ),
            AssetResolution(
                ticker="SMH",
                exchange="NASDAQ",
                asset_type=AssetType.ETF,
                status=AssetStatus.READY,
                company_name="VanEck Semiconductor ETF",
            ),
        ]
        self._assets = {asset.ticker: asset for asset in seed}

    def get(self, ticker: str) -> AssetResolution | None:
        return self._assets.get(ticker.upper())

    def save(self, asset: AssetResolution) -> AssetResolution:
        self._assets[asset.ticker.upper()] = asset
        return asset
