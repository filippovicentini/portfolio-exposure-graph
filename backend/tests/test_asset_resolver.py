from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution
from app.providers.base import AssetDataProvider
from app.repositories.asset_registry import InMemoryAssetRegistry
from app.services.asset_resolver import AssetResolver


class FakeAssetProvider(AssetDataProvider):
    def resolve(self, ticker: str) -> AssetResolution | None:
        if ticker == "ASML":
            return AssetResolution(
                ticker="ASML",
                exchange="Nasdaq",
                asset_type=AssetType.EQUITY,
                status=AssetStatus.READY,
                company_name="ASML HOLDING NV",
                cik="0000937966",
            )
        return None


def test_known_asset_resolves_from_registry():
    resolver = AssetResolver(InMemoryAssetRegistry())
    asset = resolver.resolve("nvda")

    assert asset.ticker == "NVDA"
    assert asset.status == AssetStatus.READY
    assert asset.asset_type == AssetType.EQUITY


def test_new_ticker_can_be_resolved_by_provider_and_cached():
    registry = InMemoryAssetRegistry()
    resolver = AssetResolver(registry, providers=[FakeAssetProvider()])

    asset = resolver.resolve("ASML")

    assert asset.status == AssetStatus.READY
    assert asset.asset_type == AssetType.EQUITY
    assert asset.exchange == "Nasdaq"
    assert asset.company_name == "ASML HOLDING NV"
    assert asset.cik == "0000937966"
    assert registry.get("ASML") == asset


def test_new_valid_ticker_becomes_pending_when_no_provider_can_resolve_it():
    resolver = AssetResolver(InMemoryAssetRegistry(), providers=[FakeAssetProvider()])
    asset = resolver.resolve("NOTREAL")

    assert asset.status == AssetStatus.PENDING_ENRICHMENT
    assert asset.asset_type == AssetType.UNKNOWN


def test_invalid_ticker_is_invalid():
    resolver = AssetResolver(InMemoryAssetRegistry())
    asset = resolver.resolve("@@@")

    assert asset.status == AssetStatus.INVALID


def test_etfs_are_not_hardcoded_in_default_registry():
    registry = InMemoryAssetRegistry()

    assert registry.get("QQQ") is None
    assert registry.get("SMH") is None
