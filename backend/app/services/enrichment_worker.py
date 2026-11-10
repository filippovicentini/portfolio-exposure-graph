from __future__ import annotations

import logging
import threading

from app.services.enrichment_service import EnrichmentService

logger = logging.getLogger(__name__)


class EnrichmentWorker:
    """Background thread that processes the enrichment queue periodically.

    Opt-in: started by the app lifespan only when
    ``ENRICHMENT_WORKER_INTERVAL_SECONDS`` is positive. A batch that fails is
    logged and retried on the next tick; claimed jobs whose batch crashed become
    claimable again when their lease expires.
    """

    def __init__(
        self,
        service: EnrichmentService,
        interval_seconds: float,
        batch_size: int = 10,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.service = service
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="enrichment-worker", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def run_once(self) -> None:
        try:
            result = self.service.process(limit=self.batch_size)
        except Exception:
            logger.exception("Enrichment worker batch failed")
            return
        if result.jobs_claimed:
            logger.info(
                "Enrichment batch: %d claimed, %d completed, %d requeued, %d failed",
                result.jobs_claimed,
                result.jobs_completed,
                result.jobs_requeued,
                result.jobs_failed,
            )

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval_seconds)
