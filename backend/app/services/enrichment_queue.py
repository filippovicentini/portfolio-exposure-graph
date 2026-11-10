from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.domain.enums import EnrichmentJobStatus
from app.domain.models import EnrichmentJob

ACTIVE_JOB_STATUSES = (EnrichmentJobStatus.QUEUED, EnrichmentJobStatus.PROCESSING)

# A job left in PROCESSING longer than this (e.g. the worker crashed mid-job)
# becomes claimable again.
DEFAULT_LEASE_SECONDS = 600


class EnrichmentQueue(ABC):
    @abstractmethod
    def enqueue(self, ticker: str) -> EnrichmentJob:
        """Queue a ticker for enrichment.

        At most one active (queued or processing) job exists per ticker: if one
        already exists it is returned instead of creating a duplicate.
        """
        raise NotImplementedError

    @abstractmethod
    def claim(
        self, limit: int, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> list[EnrichmentJob]:
        """Mark up to ``limit`` claimable jobs as PROCESSING and return them.

        Claimable jobs are QUEUED ones whose ``next_attempt_at`` is unset or
        due, plus PROCESSING ones whose lease expired. Oldest jobs are claimed
        first.
        """
        raise NotImplementedError

    @abstractmethod
    def save(self, job: EnrichmentJob) -> EnrichmentJob:
        raise NotImplementedError

    @abstractmethod
    def get(self, job_id: UUID) -> EnrichmentJob | None:
        raise NotImplementedError

    @abstractmethod
    def list(
        self, status: EnrichmentJobStatus | None = None, limit: int = 100
    ) -> list[EnrichmentJob]:
        """Return jobs newest first, optionally filtered by status."""
        raise NotImplementedError


class InMemoryEnrichmentQueue(EnrichmentQueue):
    def __init__(self) -> None:
        self.jobs: dict[UUID, EnrichmentJob] = {}
        self._lock = threading.Lock()

    def enqueue(self, ticker: str) -> EnrichmentJob:
        normalized = ticker.strip().upper()
        with self._lock:
            for job in self.jobs.values():
                if job.ticker == normalized and job.status in ACTIVE_JOB_STATUSES:
                    return job
            job = EnrichmentJob(ticker=normalized)
            self.jobs[job.job_id] = job
            return job

    def claim(
        self, limit: int, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> list[EnrichmentJob]:
        now = datetime.now(timezone.utc)
        lease_cutoff = now - timedelta(seconds=lease_seconds)
        with self._lock:
            claimable = [
                job
                for job in self.jobs.values()
                if (
                    job.status == EnrichmentJobStatus.QUEUED
                    and (job.next_attempt_at is None or job.next_attempt_at <= now)
                )
                or (
                    job.status == EnrichmentJobStatus.PROCESSING
                    and job.claimed_at is not None
                    and job.claimed_at < lease_cutoff
                )
            ]
            claimable.sort(key=lambda job: job.created_at)
            claimed = []
            for job in claimable[:limit]:
                updated = job.model_copy(
                    update={
                        "status": EnrichmentJobStatus.PROCESSING,
                        "claimed_at": now,
                        "updated_at": now,
                    }
                )
                self.jobs[job.job_id] = updated
                claimed.append(updated)
            return claimed

    def save(self, job: EnrichmentJob) -> EnrichmentJob:
        with self._lock:
            self.jobs[job.job_id] = job
        return job

    def get(self, job_id: UUID) -> EnrichmentJob | None:
        return self.jobs.get(job_id)

    def list(
        self, status: EnrichmentJobStatus | None = None, limit: int = 100
    ) -> list[EnrichmentJob]:
        jobs = [
            job for job in self.jobs.values() if status is None or job.status == status
        ]
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return jobs[:limit]
