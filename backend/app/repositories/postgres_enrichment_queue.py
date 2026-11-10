from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.domain.enums import EnrichmentJobStatus
from app.domain.models import EnrichmentJob
from app.repositories.postgres_schema import PostgresConnectionFactory
from app.services.enrichment_queue import DEFAULT_LEASE_SECONDS, EnrichmentQueue

# The partial unique index enforces "at most one active job per ticker" even
# with concurrent enqueues from several app processes.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS enrichment_jobs (
    job_id UUID PRIMARY KEY,
    ticker TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    document JSONB NOT NULL
);
ALTER TABLE enrichment_jobs ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS enrichment_jobs_active_ticker_idx
    ON enrichment_jobs (ticker)
    WHERE status IN ('queued', 'processing');
CREATE INDEX IF NOT EXISTS enrichment_jobs_status_created_idx
    ON enrichment_jobs (status, created_at);
"""

_UPSERT_SQL = """
INSERT INTO enrichment_jobs
    (job_id, ticker, status, created_at, claimed_at, next_attempt_at, document)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (job_id) DO UPDATE SET
    ticker = EXCLUDED.ticker,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at,
    claimed_at = EXCLUDED.claimed_at,
    next_attempt_at = EXCLUDED.next_attempt_at,
    document = EXCLUDED.document
"""


def _row(job: EnrichmentJob) -> tuple:
    return (
        job.job_id,
        job.ticker,
        job.status.value,
        job.created_at,
        job.claimed_at,
        job.next_attempt_at,
        Jsonb(job.model_dump(mode="json")),
    )


class PostgresEnrichmentQueue(EnrichmentQueue):
    """Durable enrichment queue backed by PostgreSQL.

    Jobs are claimed with ``FOR UPDATE SKIP LOCKED`` so several workers can
    process the queue without picking the same job. A claimed job carries a
    lease (``claimed_at``); if a worker dies, the job becomes claimable again
    once the lease expires.
    """

    def __init__(self, dsn: str) -> None:
        self._connections = PostgresConnectionFactory(dsn, _SCHEMA_SQL)

    @property
    def dsn(self) -> str:
        return self._connections.dsn

    def _connect(self) -> psycopg.Connection:
        return self._connections.connect()

    def enqueue(self, ticker: str) -> EnrichmentJob:
        normalized = ticker.strip().upper()
        job = EnrichmentJob(ticker=normalized)
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO enrichment_jobs
                    (job_id, ticker, status, created_at, claimed_at,
                     next_attempt_at, document)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker) WHERE status IN ('queued', 'processing')
                DO NOTHING
                RETURNING document
                """,
                _row(job),
            ).fetchone()
            if inserted is not None:
                return job
            existing = connection.execute(
                """
                SELECT document FROM enrichment_jobs
                WHERE ticker = %s AND status IN ('queued', 'processing')
                """,
                (normalized,),
            ).fetchone()
        if existing is None:
            # The active job finished between the two statements; queue anew.
            return self.enqueue(normalized)
        return EnrichmentJob.model_validate(existing[0])

    def claim(
        self, limit: int, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> list[EnrichmentJob]:
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            with connection.transaction():
                rows = connection.execute(
                    """
                    SELECT document FROM enrichment_jobs
                    WHERE (status = 'queued'
                           AND (next_attempt_at IS NULL OR next_attempt_at <= %s))
                       OR (status = 'processing'
                           AND claimed_at < %s - make_interval(secs => %s))
                    ORDER BY created_at
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (now, now, lease_seconds, limit),
                ).fetchall()
                claimed = [
                    EnrichmentJob.model_validate(row[0]).model_copy(
                        update={
                            "status": EnrichmentJobStatus.PROCESSING,
                            "claimed_at": now,
                            "updated_at": now,
                        }
                    )
                    for row in rows
                ]
                for job in claimed:
                    connection.execute(_UPSERT_SQL, _row(job))
        return claimed

    def save(self, job: EnrichmentJob) -> EnrichmentJob:
        with self._connect() as connection:
            connection.execute(_UPSERT_SQL, _row(job))
        return job

    def get(self, job_id: UUID) -> EnrichmentJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM enrichment_jobs WHERE job_id = %s", (job_id,)
            ).fetchone()
        return None if row is None else EnrichmentJob.model_validate(row[0])

    def list(
        self, status: EnrichmentJobStatus | None = None, limit: int = 100
    ) -> list[EnrichmentJob]:
        with self._connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT document FROM enrichment_jobs "
                    "ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT document FROM enrichment_jobs WHERE status = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (status.value, limit),
                ).fetchall()
        return [EnrichmentJob.model_validate(row[0]) for row in rows]
