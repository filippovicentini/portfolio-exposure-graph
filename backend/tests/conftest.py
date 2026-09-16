import pytest
from fastapi.testclient import TestClient

from app.dependencies import asset_registry, enrichment_queue, portfolio_repository
from app.main import app
from app.repositories.asset_registry import InMemoryAssetRegistry


@pytest.fixture(autouse=True)
def reset_state():
    portfolio_repository._portfolios.clear()
    enrichment_queue.jobs.clear()
    fresh_registry = InMemoryAssetRegistry()
    asset_registry._assets = fresh_registry._assets
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
