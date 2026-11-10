"""PostgreSQL portfolio repository tests.

These run against a real database only when ``TEST_DATABASE_URL`` is set, e.g.
``TEST_DATABASE_URL=postgresql://peg:peg@localhost:5432/peg``. Otherwise they are
skipped so the default suite needs no external services (see the
``postgres_dsn`` fixture in ``conftest.py``).
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from portfolio_exposure_graph.domain.enums import AssetStatus, AssetType, PortfolioStatus
from portfolio_exposure_graph.domain.models import (
    AssetResolution,
    EnrichmentJob,
    Portfolio,
    PortfolioPosition,
)


@pytest.fixture
def repository(postgres_dsn):
    from portfolio_exposure_graph.repositories.postgres_portfolio_repository import (
        PostgresPortfolioRepository,
    )

    return PostgresPortfolioRepository(dsn=postgres_dsn)


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
    from portfolio_exposure_graph.repositories.postgres_portfolio_repository import (
        PostgresPortfolioRepository,
    )

    portfolio = _portfolio("Persistent")
    repository.save(portfolio)

    reopened = PostgresPortfolioRepository(dsn=repository.dsn)

    assert reopened.get(portfolio.portfolio_id) == portfolio


def _with_asml_status(portfolio: Portfolio, status: AssetStatus) -> Portfolio:
    positions = list(portfolio.positions)
    positions[1] = positions[1].model_copy(
        update={"asset": positions[1].asset.model_copy(update={"status": status})}
    )
    return portfolio.model_copy(update={"positions": positions})


def test_find_with_unresolved_ticker_matches_pending_and_unsupported(repository):
    pending = _portfolio("Pending ASML")
    unsupported = _with_asml_status(
        _portfolio("Unsupported ASML"), AssetStatus.UNSUPPORTED
    )
    resolved = _with_asml_status(_portfolio("Resolved ASML"), AssetStatus.READY)
    for portfolio in (pending, unsupported, resolved):
        repository.save(portfolio)

    found = repository.find_with_unresolved_ticker("ASML")

    assert sorted(portfolio.name for portfolio in found) == [
        "Pending ASML",
        "Unsupported ASML",
    ]
    # NVDA is READY in every portfolio.
    assert repository.find_with_unresolved_ticker("NVDA") == []
