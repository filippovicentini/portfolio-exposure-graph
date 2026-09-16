from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import EnrichmentJob


class EnrichmentQueue(ABC):
    @abstractmethod
    def enqueue(self, ticker: str) -> EnrichmentJob:
        raise NotImplementedError


class InMemoryEnrichmentQueue(EnrichmentQueue):
    def __init__(self) -> None:
        self.jobs: list[EnrichmentJob] = []

    def enqueue(self, ticker: str) -> EnrichmentJob:
        job = EnrichmentJob(ticker=ticker)
        self.jobs.append(job)
        return job
