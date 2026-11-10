"""PostgreSQL enrichment queue tests; skipped unless TEST_DATABASE_URL is set."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.enums import AssetStatus, AssetType, EnrichmentJobStatus
from app.domain.models import AssetResolution, PortfolioCreate, PositionInput
from app.providers.base import AssetDataProvider
from app.repositories.asset_registry import InMemoryAssetRegistry
from app.services.asset_resolver import AssetResolver
from app.services.enrichment_service import EnrichmentService
from app.services.portfolio_service import PortfolioService


@pytest.fixture
def queue(postgres_dsn):
    from app.repositories.postgres_enrichment_queue import PostgresEnrichmentQueue

    return PostgresEnrichmentQueue(dsn=postgres_dsn)


def test_enqueue_keeps_one_active_job_per_ticker(queue):
    first = queue.enqueue("asml")
    second = queue.enqueue("ASML")

    assert first.job_id == second.job_id
    assert first.ticker == "ASML"
    assert queue.get(first.job_id) == first


def test_concurrent_enqueues_create_a_single_job(queue):
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: queue.enqueue("ASML"), range(16)))

    assert len({job.job_id for job in jobs}) == 1
    assert len(queue.list()) == 1


def test_enqueue_after_finished_job_creates_new_one(queue):
    first = queue.enqueue("ASML")
    queue.save(first.model_copy(update={"status": EnrichmentJobStatus.FAILED}))

    second = queue.enqueue("ASML")

    assert second.job_id != first.job_id
    assert [job.status for job in queue.list()] == [
        EnrichmentJobStatus.QUEUED,
        EnrichmentJobStatus.FAILED,
    ]


def test_claim_is_exclusive_across_concurrent_workers(queue):
    tickers = [f"T{i}" for i in range(20)]
    for ticker in tickers:
        queue.enqueue(ticker)

    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda _: queue.claim(limit=10), range(4)))

    claimed = [job.ticker for batch in batches for job in batch]
    assert sorted(claimed) == sorted(tickers)
    assert all(
        job.status == EnrichmentJobStatus.PROCESSING for batch in batches for job in batch
    )
    assert queue.claim(limit=10) == []


def test_claim_reclaims_after_lease_expiry(queue):
    queue.enqueue("ASML")
    [claimed] = queue.claim(limit=1)
    queue.save(
        claimed.model_copy(
            update={"claimed_at": datetime.now(timezone.utc) - timedelta(hours=1)}
        )
    )

    assert queue.claim(limit=1, lease_seconds=7200) == []
    assert [job.ticker for job in queue.claim(limit=1, lease_seconds=60)] == ["ASML"]


def test_list_filters_by_status(queue):
    queue.enqueue("AAA")
    done = queue.enqueue("BBB")
    queue.save(done.model_copy(update={"status": EnrichmentJobStatus.COMPLETED}))

    assert [j.ticker for j in queue.list(status=EnrichmentJobStatus.QUEUED)] == ["AAA"]
    assert len(queue.list(limit=1)) == 1


def test_end_to_end_with_postgres_portfolios(postgres_dsn, queue):
    from app.repositories.postgres_portfolio_repository import (
        PostgresPortfolioRepository,
    )

    class Provider(AssetDataProvider):
        def resolve(self, ticker):
            if ticker == "ASML":
                return AssetResolution(
                    ticker="ASML",
                    asset_type=AssetType.EQUITY,
                    status=AssetStatus.READY,
                    cik="0000937966",
                )
            return None

    portfolios = PostgresPortfolioRepository(dsn=postgres_dsn)
    registry = InMemoryAssetRegistry()
    resolver = AssetResolver(registry, providers=[])
    portfolio = PortfolioService(portfolios, resolver, queue).create(
        PortfolioCreate(
            name="Mixed",
            positions=[
                PositionInput(ticker="NVDA", weight_pct=70),
                PositionInput(ticker="ASML", weight_pct=30),
            ],
        )
    )
    resolver.providers = [Provider()]

    result = EnrichmentService(queue, resolver, portfolios).process()

    assert result.jobs_completed == 1
    assert result.portfolios_updated == 1
    stored = portfolios.get(portfolio.portfolio_id)
    assert stored.status.value == "ready"
    assert stored.positions[1].asset.cik == "0000937966"
    assert stored.enrichment_jobs[0].status == EnrichmentJobStatus.COMPLETED
