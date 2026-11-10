from __future__ import annotations

import threading

import psycopg

# Arbitrary constant shared by every process of this app. Taking it while
# running DDL serialises concurrent schema setup: ``CREATE TABLE IF NOT EXISTS``
# alone is not safe when several connections run it at the same time.
_SCHEMA_LOCK_KEY = 7_316_404_211


class PostgresConnectionFactory:
    """Open connections and make sure the given schema exists, once."""

    def __init__(self, dsn: str, schema_sql: str) -> None:
        self.dsn = dsn
        self._schema_sql = schema_sql
        self._schema_ready = False
        self._lock = threading.Lock()

    def connect(self) -> psycopg.Connection:
        connection = psycopg.connect(self.dsn)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    with connection.transaction():
                        connection.execute(
                            "SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,)
                        )
                        connection.execute(self._schema_sql)
                    self._schema_ready = True
        return connection
