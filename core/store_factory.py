"""Choose the SQLite or PostgreSQL/Supabase repository from configuration."""

from __future__ import annotations

import os
from typing import Union

from core.deal_store import DealRepository
from core.postgres_store import PostgresDealRepository

Repository = Union[DealRepository, PostgresDealRepository]


def get_deal_repository() -> Repository:
    url = os.environ.get("DATABASE_URL", "").strip()
    url = url.replace("postgresql+psycopg://", "postgresql://")
    if url.startswith(("postgres://", "postgresql://", "postgresql+")):
        return PostgresDealRepository(url)
    return DealRepository()
