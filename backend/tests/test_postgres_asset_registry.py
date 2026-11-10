"""PostgreSQL asset registry tests; skipped unless TEST_DATABASE_URL is set."""

import pytest

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution


@pytest.fixture
def registry(postgres_dsn):
    from app.repositories.postgres_asset_registry import PostgresAssetRegistry

    return PostgresAssetRegistry(dsn=postgres_dsn)


ASML = AssetResolution(
    ticker="ASML",
    exchange="Nasdaq",
    asset_type=AssetType.EQUITY,
    status=AssetStatus.READY,
    company_name="ASML HOLDING NV",
    cik="0000937966",
)


def test_save_and_get_round_trip(registry):
    registry.save(ASML)

    assert registry.get("ASML") == ASML
    assert registry.get("asml") == ASML
    assert registry.get("NOPE") is None


def test_save_is_an_upsert(registry):
    registry.save(
        AssetResolution(ticker="ASML", status=AssetStatus.PENDING_ENRICHMENT)
    )
    registry.save(ASML)

    assert registry.get("ASML") == ASML


def test_dev_seeds_are_available(registry):
    assert registry.get("NVDA").status == AssetStatus.READY
    assert registry.get("MSFT").asset_type == AssetType.EQUITY
    assert registry.get("QQQ") is None  # ETFs are never seeded


def test_seeds_do_not_overwrite_stored_assets(registry):
    from app.repositories.postgres_asset_registry import PostgresAssetRegistry

    richer = AssetResolution(
        ticker="NVDA",
        exchange="Nasdaq",
        asset_type=AssetType.EQUITY,
        status=AssetStatus.READY,
        company_name="NVIDIA CORP",
        cik="0001045810",
    )
    registry.save(richer)

    reopened = PostgresAssetRegistry(dsn=registry.dsn)

    assert reopened.get("NVDA") == richer


def test_assets_survive_a_new_registry_instance(registry):
    from app.repositories.postgres_asset_registry import PostgresAssetRegistry

    registry.save(ASML)

    assert PostgresAssetRegistry(dsn=registry.dsn).get("ASML") == ASML
