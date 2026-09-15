"""Database bootstrapping.

If DATABASE_URL is configured, we use a real asyncpg connection pool
against PostgreSQL. If it is not configured, the app still starts (per
the project's "never block the whole app on one missing config value"
principle) but falls back to an in-memory store — clearly logged as
DEMO MODE, since that data does not survive a restart.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .config import settings
from .repositories import InMemoryRepository, PostgresRepository, Repository

log = logging.getLogger("smart-glasses.database")

_repository: Optional[Repository] = None
_pg_pool = None  # asyncpg.Pool, created lazily to avoid import cost in demo mode


async def init_repository() -> Repository:
    global _repository, _pg_pool

    if not settings.database_url:
        log.warning("Menggunakan penyimpanan sementara (demo mode, non-persisten).")
        _repository = InMemoryRepository()
        return _repository

    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "DATABASE_URL diatur tetapi paket 'asyncpg' belum terpasang. "
            "Jalankan: pip install -r requirements.txt"
        ) from exc

    _pg_pool = await asyncpg.create_pool(
    settings.database_url, min_size=1, max_size=10, statement_cache_size=0
    )
    await _ensure_schema(_pg_pool)
    _repository = PostgresRepository(_pg_pool)
    log.info("Terhubung ke PostgreSQL.")
    return _repository


async def _ensure_schema(pool) -> None:
    """Apply schema.sql on startup so a fresh database self-provisions."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def close_repository() -> None:
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None


def get_repository() -> Repository:
    if _repository is None:
        raise RuntimeError("Repository belum diinisialisasi — panggil init_repository() saat startup.")
    return _repository
