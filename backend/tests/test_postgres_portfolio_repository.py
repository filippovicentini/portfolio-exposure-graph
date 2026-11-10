"""PostgreSQL portfolio repository tests.

These run against a real database only when ``TEST_DATABASE_URL`` is set, e.g.
``TEST_DATABASE_URL=postgresql://peg:peg@localhost:5432/peg``. Otherwise they are
skipped so the default suite needs no external services. Each run uses a
dedicated schema that is dropped afterwards.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.domain.enums import AssetStatus, AssetType, PortfolioStatus
from app.domain.models import (
    AssetResolution,
    EnrichmentJob,
    Portfolio,
    PortfolioPosition,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set"
)


@pytest.fixture
def repository():
    import psycopg

    from app.repositories.postgres_portfolio_repository import (
        PostgresPortfolioRepository,
    )

    schema = f"test_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
    separator = "&" if "?" in TEST_DATABASE_URL else "?"
    dsn = f"{TEST_DATABASE_URL}{separator}options=-csearch_path%3D{schema}"

    yield PostgresPortfolioRepository(dsn=dsn)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _portfolio(name: str, created_at: datetime | None = None) -> Portfolio:
    return Portfolio(
        name=name,
        status=PortfolioStatus.PARTIALLY_READY,
        positions=[
            PortfolioPosition(
                ticker="NVDA",
                weight_pct=70,
                asset=AssetResolution(
                    ticker="NVDA",
                    exchange="NASDAQ",
                    asset_type=AssetType.EQUITY,
                    status=AssetStatus.READY,
                    company_name="NVIDIA Corporation",
                    cik="0001045810",
                ),
            ),
            PortfolioPosition(
                ticker="ASML",
                weight_pct=30,
                asset=AssetResolution(
                    ticker="ASML", status=AssetStatus.PENDING_ENRICHMENT
                ),
            ),
        ],
        enrichment_jobs=[EnrichmentJob(ticker="ASML")],
        **({"created_at": created_at} if created_at else {}),
    )


def test_save_and_get_round_trips_full_portfolio(repository):
    portfolio = _portfolio("Core")

    repository.save(portfolio)
    loaded = repository.get(portfolio.portfolio_id)

    assert loaded == portfolio


def test_get_missing_portfolio_returns_none(repository):
    assert repository.get(uuid4()) is None


def test_save_is_an_upsert(repository):
    portfolio = _portfolio("Core")
    repository.save(portfolio)

    updated = portfolio.model_copy(
        update={"name": "Renamed", "status": PortfolioStatus.READY}
    )
    repository.save(updated)

    assert repository.get(portfolio.portfolio_id) == updated
    assert len(repository.list()) == 1


def test_list_returns_newest_first_with_limit(repository):
    now = datetime.now(timezone.utc)
    older = _portfolio("Older", created_at=now - timedelta(minutes=5))
    newer = _portfolio("Newer", created_at=now)
    repository.save(older)
    repository.save(newer)

    assert [p.name for p in repository.list()] == ["Newer", "Older"]
    assert [p.name for p in repository.list(limit=1)] == ["Newer"]


def test_portfolios_survive_a_new_repository_instance(repository):
    from app.repositories.postgres_portfolio_repository import (
        PostgresPortfolioRepository,
    )

    portfolio = _portfolio("Persistent")
    repository.save(portfolio)

    reopened = PostgresPortfolioRepository(dsn=repository._dsn)

    assert reopened.get(portfolio.portfolio_id) == portfolio
