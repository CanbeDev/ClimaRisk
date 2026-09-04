"""Database connection pool."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool
from psycopg2.extensions import connection as PgConnection

from app.config import get_settings

_connection_pool: pool.SimpleConnectionPool | None = None


def init_pool(minconn: int = 1, maxconn: int = 5) -> None:
    global _connection_pool
    if _connection_pool is not None:
        return
    settings = get_settings()
    _connection_pool = pool.SimpleConnectionPool(
        minconn,
        maxconn,
        dsn=settings.database_url,
    )


def close_pool() -> None:
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None


@contextmanager
def get_connection() -> Generator[PgConnection, None, None]:
    if _connection_pool is None:
        init_pool()
    assert _connection_pool is not None
    conn = _connection_pool.getconn()
    try:
        yield conn
    finally:
        _connection_pool.putconn(conn)


def check_db_connection() -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except psycopg2.Error:
        return False
