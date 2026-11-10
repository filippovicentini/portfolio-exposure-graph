from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.domain.enums import AssetStatus, EnrichmentJobStatus, PortfolioStatus
from app.domain.models import (
    AssetResolution,
    EnrichmentJob,
    EnrichmentProcessResult,
    Portfolio,
)
from app.repositories.portfolio_repository import (
    UNRESOLVED_ASSET_STATUSES,
    PortfolioRepository,
)
from app.services.asset_resolver import AssetResolver
from app.services.enrichment_queue import DEFAULT_LEASE_SECONDS, EnrichmentQueue

logger = logging.getLogger(__name__)

NOT_RECOGNISED_ERROR = "No asset provider recognised the ticker"

# Asset states that keep a portfolio PARTIALLY_READY.
_NOT_READY_ASSET_STATUSES = {AssetStatus.PENDING_ENRICHMENT, AssetStatus.UNSUPPORTED}


class EnrichmentService:
    """Process queued ticker-enrichment jobs.

    Each claimed job retries the asset providers for its ticker. Outcomes:

    - resolved: the job is COMPLETED, the asset registry is updated and every
      portfolio holding the ticker unresolved (PENDING_ENRICHMENT, or
      UNSUPPORTED from an earlier failed job) gets the resolved asset.
    - not recognised by any provider, or a provider error: the job goes back to
      QUEUED until ``max_attempts`` is reached, then it is FAILED. A requeued
      job is not claimable before ``next_attempt_at``: the delay starts at
      ``retry_base_seconds`` and doubles per attempt, capped at
      ``retry_max_seconds``, so a short outage does not burn every attempt.
    - on the final attempt, if every provider answered and none recognised the
      ticker, the asset becomes UNSUPPORTED. If the last attempt hit provider
      errors (network, missing credentials), the asset stays
      PENDING_ENRICHMENT: we do not know that the ticker is unsupported, and a
      new portfolio holding it will queue a fresh job.

    Portfolios also keep an up-to-date snapshot of their enrichment jobs.
    """

    def __init__(
        self,
        queue: EnrichmentQueue,
        asset_resolver: AssetResolver,
        portfolio_repository: PortfolioRepository,
        max_attempts: int = 3,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        retry_base_seconds: float = 60.0,
        retry_max_seconds: float = 3600.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_base_seconds < 0 or retry_max_seconds < retry_base_seconds:
            raise ValueError(
                "retry delays must satisfy 0 <= retry_base_seconds <= retry_max_seconds"
            )
        self.queue = queue
        self.asset_resolver = asset_resolver
        self.portfolio_repository = portfolio_repository
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds

    def retry_delay(self, attempts: int) -> timedelta:
        """Delay before the next attempt after ``attempts`` failed ones."""
        seconds = min(
            self.retry_base_seconds * 2 ** max(attempts - 1, 0),
            self.retry_max_seconds,
        )
        return timedelta(seconds=seconds)

    def process(self, limit: int = 10) -> EnrichmentProcessResult:
        claimed = self.queue.claim(limit, lease_seconds=self.lease_seconds)
        counts = {status: 0 for status in EnrichmentJobStatus}
        updated_portfolio_ids = set()
        processed: list[EnrichmentJob] = []

        for job in claimed:
            finished, asset = self._process_job(job)
            self.queue.save(finished)
            counts[finished.status] += 1
            processed.append(finished)
            for portfolio in self._update_portfolios(finished, asset):
                updated_portfolio_ids.add(portfolio.portfolio_id)

        return EnrichmentProcessResult(
            jobs_claimed=len(claimed),
            jobs_completed=counts[EnrichmentJobStatus.COMPLETED],
            jobs_requeued=counts[EnrichmentJobStatus.QUEUED],
            jobs_failed=counts[EnrichmentJobStatus.FAILED],
            portfolios_updated=len(updated_portfolio_ids),
            jobs=processed,
        )

    def _process_job(
        self, job: EnrichmentJob
    ) -> tuple[EnrichmentJob, AssetResolution | None]:
        attempts = job.attempts + 1
        now = datetime.now(timezone.utc)
        common = {
            "attempts": attempts,
            "updated_at": now,
            "claimed_at": None,
            "next_attempt_at": None,
        }

        resolved, errors = self.asset_resolver.enrich(job.ticker)
        if resolved is not None:
            return (
                job.model_copy(
                    update={
                        **common,
                        "status": EnrichmentJobStatus.COMPLETED,
                        "last_error": None,
                        "resolved_asset_type": resolved.asset_type,
                    }
                ),
                resolved,
            )

        last_error = "; ".join(errors) if errors else NOT_RECOGNISED_ERROR
        if attempts < self.max_attempts:
            logger.info(
                "Enrichment of %s not resolved (attempt %d/%d): %s",
                job.ticker,
                attempts,
                self.max_attempts,
                last_error,
            )
            return (
                job.model_copy(
                    update={
                        **common,
                        "status": EnrichmentJobStatus.QUEUED,
                        "last_error": last_error,
                        "next_attempt_at": now + self.retry_delay(attempts),
                    }
                ),
                None,
            )

        logger.warning(
            "Enrichment of %s failed after %d attempts: %s",
            job.ticker,
            attempts,
            last_error,
        )
        asset = None if errors else self.asset_resolver.mark_unsupported(job.ticker)
        return (
            job.model_copy(
                update={
                    **common,
                    "status": EnrichmentJobStatus.FAILED,
                    "last_error": last_error,
                }
            ),
            asset,
        )

    def _update_portfolios(
        self, job: EnrichmentJob, asset: AssetResolution | None
    ) -> list[Portfolio]:
        updated = []
        for portfolio in self.portfolio_repository.find_with_unresolved_ticker(
            job.ticker
        ):
            positions = [
                position.model_copy(update={"asset": asset})
                if asset is not None
                and position.ticker == job.ticker
                and position.asset.status in UNRESOLVED_ASSET_STATUSES
                else position
                for position in portfolio.positions
            ]
            jobs = [
                job if existing.job_id == job.job_id else existing
                for existing in portfolio.enrichment_jobs
            ]
            if all(existing.job_id != job.job_id for existing in jobs):
                jobs.append(job)
            status = (
                PortfolioStatus.PARTIALLY_READY
                if any(
                    position.asset.status in _NOT_READY_ASSET_STATUSES
                    for position in positions
                )
                else PortfolioStatus.READY
            )
            updated.append(
                self.portfolio_repository.save(
                    portfolio.model_copy(
                        update={
                            "positions": positions,
                            "enrichment_jobs": jobs,
                            "status": status,
                        }
                    )
                )
            )
        return updated
