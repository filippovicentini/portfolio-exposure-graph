from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from app.domain.models import AssetResolution
from app.repositories.asset_registry import AssetRegistry, default_seed_assets
from app.repositories.postgres_schema import PostgresConnectionFactory

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS assets (
    ticker TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    document JSONB NOT NULL
);
"""


class PostgresAssetRegistry(AssetRegistry):
    """Asset registry persisted in PostgreSQL, keyed by normalized ticker.

    The full ``AssetResolution`` is stored as JSONB. The development seeds are
    inserted once and never overwrite a stored entry, so an asset that a
    provider resolved with richer data (e.g. a CIK) keeps it.
    """

    def __init__(self, dsn: str) -> None:
        self._connections = PostgresConnectionFactory(dsn, _SCHEMA_SQL)
        self._seeded = False

    @property
    def dsn(self) -> str:
        return self._connections.dsn

    def _connect(self) -> psycopg.Connection:
        connection = self._connections.connect()
        if not self._seeded:
            for asset in default_seed_assets():
                connection.execute(
                    """
                    INSERT INTO assets (ticker, status, asset_type, document)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ticker) DO NOTHING
                    """,
                    (
                        asset.ticker.upper(),
                        asset.status.value,
                        asset.asset_type.value,
                        Jsonb(asset.model_dump(mode="json")),
                    ),
                )
            connection.commit()
            self._seeded = True
        return connection

    def get(self, ticker: str) -> AssetResolution | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM assets WHERE ticker = %s", (ticker.upper(),)
            ).fetchone()
        return None if row is None else AssetResolution.model_validate(row[0])

    def save(self, asset: AssetResolution) -> AssetResolution:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assets (ticker, status, asset_type, updated_at, document)
                VALUES (%s, %s, %s, now(), %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    status = EXCLUDED.status,
                    asset_type = EXCLUDED.asset_type,
                    updated_at = EXCLUDED.updated_at,
                    document = EXCLUDED.document
                """,
                (
                    asset.ticker.upper(),
                    asset.status.value,
                    asset.asset_type.value,
                    Jsonb(asset.model_dump(mode="json")),
                ),
            )
        return asset
