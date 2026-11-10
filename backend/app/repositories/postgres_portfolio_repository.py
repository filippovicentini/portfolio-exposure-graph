from __future__ import annotations

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.domain.models import Portfolio
from app.repositories.portfolio_repository import PortfolioRepository

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    document JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS portfolios_created_at_idx
    ON portfolios (created_at DESC);
"""


class PostgresPortfolioRepository(PortfolioRepository):
    """Persist portfolios in PostgreSQL.

    The full validated ``Portfolio`` model is stored as a JSONB document, with a
    few scalar columns duplicated for listing and ordering. Positions and asset
    resolutions are a snapshot taken at creation time, so a document store keeps
    the schema small without losing information.

    Connections are opened per call: portfolio reads and writes are infrequent
    compared with graph work, and this avoids holding a pool for a local app.
    The table is created lazily on first use so the app can start before
    PostgreSQL is reachable.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False

    def _connect(self) -> psycopg.Connection:
        connection = psycopg.connect(self._dsn)
        if not self._schema_ready:
            with connection.transaction():
                connection.execute(_SCHEMA_SQL)
            self._schema_ready = True
        return connection

    def save(self, portfolio: Portfolio) -> Portfolio:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO portfolios (portfolio_id, name, status, created_at, document)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (portfolio_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at,
                    document = EXCLUDED.document
                """,
                (
                    portfolio.portfolio_id,
                    portfolio.name,
                    portfolio.status.value,
                    portfolio.created_at,
                    Jsonb(portfolio.model_dump(mode="json")),
                ),
            )
        return portfolio

    def get(self, portfolio_id: UUID) -> Portfolio | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM portfolios WHERE portfolio_id = %s",
                (portfolio_id,),
            ).fetchone()
        if row is None:
            return None
        return Portfolio.model_validate(row[0])

    def list(self, limit: int = 50) -> list[Portfolio]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document FROM portfolios ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [Portfolio.model_validate(row[0]) for row in rows]
