from app.domain.enums import AssetStatus, AssetType
from app.repositories.asset_registry import InMemoryAssetRegistry
from app.services.asset_resolver import AssetResolver


def test_known_asset_resolves_from_registry():
    resolver = AssetResolver(InMemoryAssetRegistry())
    asset = resolver.resolve("nvda")

    assert asset.ticker == "NVDA"
    assert asset.status == AssetStatus.READY
    assert asset.asset_type == AssetType.EQUITY


def test_new_valid_ticker_becomes_pending():
    resolver = AssetResolver(InMemoryAssetRegistry())
    asset = resolver.resolve("ASML")

    assert asset.status == AssetStatus.PENDING_ENRICHMENT
    assert asset.asset_type == AssetType.UNKNOWN


def test_invalid_ticker_is_invalid():
    resolver = AssetResolver(InMemoryAssetRegistry())
    asset = resolver.resolve("@@@")

    assert asset.status == AssetStatus.INVALID
