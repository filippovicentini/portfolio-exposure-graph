import time
from datetime import datetime, timedelta, timezone

import pytest

from app.dependencies import asset_resolver
from app.domain.enums import (
    AssetStatus,
    AssetType,
    EnrichmentJobStatus,
    PortfolioStatus,
)
from app.domain.models import AssetResolution, PortfolioCreate, PositionInput
from app.providers.base import AssetDataProvider
from app.repositories.asset_registry import InMemoryAssetRegistry
from app.repositories.portfolio_repository import InMemoryPortfolioRepository
from app.services.asset_resolver import AssetResolver
from app.services.enrichment_queue import InMemoryEnrichmentQueue
from app.services.enrichment_service import NOT_RECOGNISED_ERROR, EnrichmentService
from app.services.enrichment_worker import EnrichmentWorker
from app.services.portfolio_service import PortfolioService

ASML = AssetResolution(
    ticker="ASML",
    exchange="Nasdaq",
    asset_type=AssetType.EQUITY,
    status=AssetStatus.READY,
    company_name="ASML HOLDING NV",
    cik="0000937966",
)


class SwitchableProvider(AssetDataProvider):
    """Recognises nothing until ``known`` is filled; can be made to raise."""

    def __init__(self) -> None:
        self.known: dict[str, AssetResolution] = {}
        self.error: Exception | None = None
        self.calls: list[str] = []

    def resolve(self, ticker: str) -> AssetResolution | None:
        self.calls.append(ticker)
        if self.error is not None:
            raise self.error
        return self.known.get(ticker)


@pytest.fixture
def setup():
    provider = SwitchableProvider()
    registry = InMemoryAssetRegistry()
    resolver = AssetResolver(registry, providers=[provider])
    queue = InMemoryEnrichmentQueue()
    portfolios = InMemoryPortfolioRepository()
    portfolio_service = PortfolioService(portfolios, resolver, queue)
    # No backoff here: these tests exercise the job lifecycle; backoff has its own tests.
    service = EnrichmentService(
        queue, resolver, portfolios, max_attempts=2, retry_base_seconds=0
    )
    return provider, registry, queue, portfolios, portfolio_service, service


def _create(portfolio_service, name="Mixed", tickers=(("NVDA", 70), ("ASML", 30))):
    return portfolio_service.create(
        PortfolioCreate(
            name=name,
            positions=[PositionInput(ticker=t, weight_pct=w) for t, w in tickers],
        )
    )


# --- queue -----------------------------------------------------------------


def test_queue_keeps_one_active_job_per_ticker():
    queue = InMemoryEnrichmentQueue()

    first = queue.enqueue("asml")
    second = queue.enqueue("ASML")

    assert first.job_id == second.job_id
    assert first.ticker == "ASML"
    assert len(queue.list()) == 1


def test_queue_creates_new_job_once_previous_finished():
    queue = InMemoryEnrichmentQueue()
    first = queue.enqueue("ASML")
    queue.save(first.model_copy(update={"status": EnrichmentJobStatus.FAILED}))

    second = queue.enqueue("ASML")

    assert second.job_id != first.job_id


def test_claim_marks_jobs_processing_oldest_first_and_respects_limit():
    queue = InMemoryEnrichmentQueue()
    older = queue.enqueue("AAA")
    queue.enqueue("BBB")

    claimed = queue.claim(limit=1)

    assert [job.job_id for job in claimed] == [older.job_id]
    assert claimed[0].status == EnrichmentJobStatus.PROCESSING
    assert claimed[0].claimed_at is not None
    assert [job.ticker for job in queue.claim(limit=5)] == ["BBB"]
    assert queue.claim(limit=5) == []


def test_claim_reclaims_processing_job_after_lease_expires():
    queue = InMemoryEnrichmentQueue()
    queue.enqueue("ASML")
    [claimed] = queue.claim(limit=1)
    queue.save(
        claimed.model_copy(
            update={"claimed_at": datetime.now(timezone.utc) - timedelta(hours=1)}
        )
    )

    assert queue.claim(limit=1, lease_seconds=3600 * 2) == []
    assert [job.ticker for job in queue.claim(limit=1, lease_seconds=60)] == ["ASML"]


def test_list_filters_by_status():
    queue = InMemoryEnrichmentQueue()
    queue.enqueue("AAA")
    done = queue.enqueue("BBB")
    queue.save(done.model_copy(update={"status": EnrichmentJobStatus.COMPLETED}))

    assert [j.ticker for j in queue.list(status=EnrichmentJobStatus.QUEUED)] == ["AAA"]


# --- service ---------------------------------------------------------------


def test_resolved_job_completes_and_updates_portfolio_and_registry(setup):
    provider, registry, queue, portfolios, portfolio_service, service = setup
    portfolio = _create(portfolio_service)
    assert portfolio.status == PortfolioStatus.PARTIALLY_READY
    provider.known["ASML"] = ASML

    result = service.process()

    assert result.jobs_claimed == 1
    assert result.jobs_completed == 1
    assert result.portfolios_updated == 1
    [job] = result.jobs
    assert job.status == EnrichmentJobStatus.COMPLETED
    assert job.attempts == 1
    assert job.resolved_asset_type == AssetType.EQUITY
    assert job.claimed_at is None
    assert queue.get(job.job_id) == job

    updated = portfolios.get(portfolio.portfolio_id)
    assert updated.status == PortfolioStatus.READY
    assert updated.positions[1].asset.status == AssetStatus.READY
    assert updated.positions[1].asset.cik == "0000937966"
    assert updated.positions[1].weight_pct == 30
    assert updated.enrichment_jobs == [job]
    assert registry.get("ASML").status == AssetStatus.READY


def test_pending_registry_entry_does_not_block_retry(setup):
    provider, registry, _queue, _portfolios, portfolio_service, service = setup
    _create(portfolio_service)
    assert registry.get("ASML").status == AssetStatus.PENDING_ENRICHMENT
    provider.known["ASML"] = ASML

    service.process()

    assert registry.get("ASML").status == AssetStatus.READY


def test_one_job_serves_every_portfolio_holding_the_ticker(setup):
    provider, _registry, queue, portfolios, portfolio_service, service = setup
    first = _create(portfolio_service, "One")
    second = _create(portfolio_service, "Two", (("ASML", 100),))
    assert first.enrichment_jobs[0].job_id == second.enrichment_jobs[0].job_id
    provider.known["ASML"] = ASML

    result = service.process()

    assert result.jobs_claimed == 1
    assert result.portfolios_updated == 2
    for portfolio_id in (first.portfolio_id, second.portfolio_id):
        assert portfolios.get(portfolio_id).status == PortfolioStatus.READY


def test_unrecognised_ticker_is_requeued_then_marked_unsupported(setup):
    _provider, registry, queue, portfolios, portfolio_service, service = setup
    portfolio = _create(portfolio_service)

    first = service.process()
    assert first.jobs_requeued == 1
    [job] = first.jobs
    assert job.status == EnrichmentJobStatus.QUEUED
    assert job.attempts == 1
    assert job.last_error == NOT_RECOGNISED_ERROR
    # The portfolio's job snapshot follows the queue.
    assert portfolios.get(portfolio.portfolio_id).enrichment_jobs == [job]

    second = service.process()
    assert second.jobs_failed == 1
    [job] = second.jobs
    assert job.status == EnrichmentJobStatus.FAILED
    assert job.attempts == 2

    updated = portfolios.get(portfolio.portfolio_id)
    assert updated.positions[1].asset.status == AssetStatus.UNSUPPORTED
    assert updated.status == PortfolioStatus.PARTIALLY_READY
    assert updated.enrichment_jobs == [job]
    assert registry.get("ASML").status == AssetStatus.UNSUPPORTED

    assert service.process().jobs_claimed == 0


def test_provider_errors_fail_job_but_keep_asset_pending(setup):
    provider, registry, queue, portfolios, portfolio_service, service = setup
    portfolio = _create(portfolio_service)
    provider.error = RuntimeError("SEC_USER_AGENT is required")

    service.process()
    result = service.process()

    [job] = result.jobs
    assert job.status == EnrichmentJobStatus.FAILED
    assert "SwitchableProvider: SEC_USER_AGENT is required" in job.last_error
    updated = portfolios.get(portfolio.portfolio_id)
    assert updated.positions[1].asset.status == AssetStatus.PENDING_ENRICHMENT
    assert updated.enrichment_jobs == [job]
    assert registry.get("ASML").status == AssetStatus.PENDING_ENRICHMENT

    # A later portfolio holding the ticker queues a fresh job.
    provider.error = None
    provider.known["ASML"] = ASML
    later = _create(portfolio_service, "Later", (("ASML", 100),))
    assert later.enrichment_jobs[0].job_id != job.job_id
    service.process()
    assert portfolios.get(portfolio.portfolio_id).status == PortfolioStatus.READY
    assert portfolios.get(later.portfolio_id).status == PortfolioStatus.READY


def test_no_providers_configured_is_reported_as_error():
    resolver = AssetResolver(InMemoryAssetRegistry(), providers=[])
    queue = InMemoryEnrichmentQueue()
    service = EnrichmentService(
        queue, resolver, InMemoryPortfolioRepository(), max_attempts=1
    )
    queue.enqueue("ASML")

    [job] = service.process().jobs

    assert job.status == EnrichmentJobStatus.FAILED
    assert job.last_error == "No asset providers are configured"
    assert resolver.registry.get("ASML") is None


def test_max_attempts_must_be_positive(setup):
    _provider, _registry, queue, portfolios, _ps, service = setup
    with pytest.raises(ValueError):
        EnrichmentService(queue, service.asset_resolver, portfolios, max_attempts=0)


def test_worker_run_once_processes_and_survives_errors(setup):
    provider, _registry, queue, _portfolios, portfolio_service, service = setup
    _create(portfolio_service)
    provider.known["ASML"] = ASML
    worker = EnrichmentWorker(service, interval_seconds=60)

    worker.run_once()
    assert queue.list()[0].status == EnrichmentJobStatus.COMPLETED

    def boom(limit):
        raise RuntimeError("db down")

    service.process = boom
    worker.run_once()  # logged, not raised


def test_worker_start_and_stop(setup):
    provider, _registry, queue, _portfolios, portfolio_service, service = setup
    _create(portfolio_service)
    provider.known["ASML"] = ASML
    worker = EnrichmentWorker(service, interval_seconds=0.01)

    worker.start()
    try:
        for _ in range(200):
            if queue.list()[0].status == EnrichmentJobStatus.COMPLETED:
                break
            time.sleep(0.01)
    finally:
        worker.stop()

    assert queue.list()[0].status == EnrichmentJobStatus.COMPLETED


# --- backoff ---------------------------------------------------------------


def test_claim_skips_queued_jobs_not_yet_due():
    queue = InMemoryEnrichmentQueue()
    now = datetime.now(timezone.utc)
    later = queue.enqueue("LATER")
    queue.save(later.model_copy(update={"next_attempt_at": now + timedelta(minutes=5)}))
    due = queue.enqueue("DUE")
    queue.save(due.model_copy(update={"next_attempt_at": now - timedelta(seconds=1)}))

    assert [job.ticker for job in queue.claim(limit=10)] == ["DUE"]


def test_retry_delay_doubles_and_is_capped():
    service = EnrichmentService(
        InMemoryEnrichmentQueue(),
        AssetResolver(InMemoryAssetRegistry()),
        InMemoryPortfolioRepository(),
        retry_base_seconds=60,
        retry_max_seconds=200,
    )

    assert [service.retry_delay(n).total_seconds() for n in (1, 2, 3, 4)] == [
        60,
        120,
        200,
        200,
    ]


def test_retry_delay_settings_are_validated():
    args = (
        InMemoryEnrichmentQueue(),
        AssetResolver(InMemoryAssetRegistry()),
        InMemoryPortfolioRepository(),
    )
    with pytest.raises(ValueError):
        EnrichmentService(*args, retry_base_seconds=-1)
    with pytest.raises(ValueError):
        EnrichmentService(*args, retry_base_seconds=100, retry_max_seconds=10)


def test_requeued_job_waits_for_backoff_before_next_attempt():
    provider = SwitchableProvider()
    resolver = AssetResolver(InMemoryAssetRegistry(), providers=[provider])
    queue = InMemoryEnrichmentQueue()
    service = EnrichmentService(
        queue,
        resolver,
        InMemoryPortfolioRepository(),
        max_attempts=3,
        retry_base_seconds=60,
    )
    queue.enqueue("ASML")

    before = datetime.now(timezone.utc)
    [job] = service.process().jobs
    assert job.status == EnrichmentJobStatus.QUEUED
    assert job.next_attempt_at >= before + timedelta(seconds=60)

    # Not due yet: nothing is claimed and the provider is not called again.
    assert service.process().jobs_claimed == 0
    assert provider.calls == ["ASML"]

    # Once due, the job is retried and the delay doubles.
    queue.save(job.model_copy(update={"next_attempt_at": before}))
    provider.known["ASML"] = ASML
    [done] = service.process().jobs
    assert done.status == EnrichmentJobStatus.COMPLETED
    assert done.next_attempt_at is None


# --- API -------------------------------------------------------------------


def test_enrichment_api_processes_queue_and_updates_portfolio(client):
    created = client.post(
        "/api/v1/portfolios",
        json={
            "name": "Mixed",
            "positions": [
                {"ticker": "NVDA", "weight_pct": 70},
                {"ticker": "ASML", "weight_pct": 30},
            ],
        },
    ).json()
    job_id = created["enrichment_jobs"][0]["job_id"]

    queued = client.get("/api/v1/enrichment-jobs", params={"status": "queued"})
    assert [job["job_id"] for job in queued.json()] == [job_id]

    provider = SwitchableProvider()
    provider.known["ASML"] = ASML
    asset_resolver.providers = [provider]

    response = client.post("/api/v1/enrichment-jobs/process", params={"limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["jobs_completed"] == 1
    assert body["portfolios_updated"] == 1

    job = client.get(f"/api/v1/enrichment-jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["attempts"] == 1

    portfolio = client.get(f"/api/v1/portfolios/{created['portfolio_id']}").json()
    assert portfolio["status"] == "ready"
    assert portfolio["positions"][1]["asset"]["cik"] == "0000937966"
    assert portfolio["enrichment_jobs"][0]["status"] == "completed"


def test_enrichment_api_missing_job_is_404(client):
    response = client.get(
        "/api/v1/enrichment-jobs/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


def test_enrichment_api_rejects_bad_status_filter(client):
    response = client.get("/api/v1/enrichment-jobs", params={"status": "bogus"})
    assert response.status_code == 422
