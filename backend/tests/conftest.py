import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    asset_registry,
    asset_resolver,
    enrichment_queue,
    portfolio_repository,
)
from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution
from app.main import app
from app.repositories.asset_registry import InMemoryAssetRegistry


@pytest.fixture(autouse=True)
def reset_state():
    portfolio_repository._portfolios.clear()
    enrichment_queue.jobs.clear()

    fresh_registry = InMemoryAssetRegistry()
    fresh_registry.save(
        AssetResolution(
            ticker="QQQ",
            exchange="NASDAQ",
            asset_type=AssetType.ETF,
            status=AssetStatus.READY,
            company_name="Invesco QQQ Trust",
        )
    )
    asset_registry._assets = fresh_registry._assets

    original_providers = asset_resolver.providers
    asset_resolver.providers = []

    yield

    asset_resolver.providers = original_providers


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(name="portfolio_repository")
def portfolio_repository_fixture():
    return portfolio_repository


@pytest.fixture
def postgres_dsn():
    """DSN pointing at a fresh, temporary schema in ``TEST_DATABASE_URL``.

    Skips the test when ``TEST_DATABASE_URL`` is not set, so the default suite
    needs no PostgreSQL. The schema is dropped afterwards.
    """
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    schema = f"test_{uuid4().hex}"
    with psycopg.connect(base_url, autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
    separator = "&" if "?" in base_url else "?"
    yield f"{base_url}{separator}options=-csearch_path%3D{schema}"
    with psycopg.connect(base_url, autocommit=True) as connection:
        connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
