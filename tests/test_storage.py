import os
from pathlib import Path
from unittest.mock import patch

from core.deal_store import DealRepository
from core.postgres_store import PostgresDealRepository
from core.state import NegotiationDealState
from core.store_factory import get_deal_repository


def test_sqlite_factory_and_retention(tmp_path):
    with patch.dict(
        os.environ,
        {"REDLINER_DB_PATH": str(tmp_path / "deals.db"), "DATABASE_URL": ""},
    ):
        repository = get_deal_repository()
    assert isinstance(repository, DealRepository)
    result = repository.purge(365)
    assert set(result) == {"events", "snapshots", "outbound_messages"}


def test_postgres_repository_requires_dsn():
    with patch.dict(os.environ, {"DATABASE_URL": ""}):
        try:
            PostgresDealRepository()
        except ValueError as exc:
            assert "DATABASE_URL" in str(exc)
        else:
            raise AssertionError("Expected a missing DATABASE_URL error")


def test_sqlite_outbound_message_matching(tmp_path):
    repository = DealRepository(tmp_path / "deals.db")
    repository.save(
        NegotiationDealState(
            deal_id="DEAL-THREAD",
            source_contract_filename="contract.docx",
        )
    )
    repository.record_outbound(
        message_id="<thread-1@redliner.local>",
        deal_id="DEAL-THREAD",
        recipient="vendor@example.com",
        subject="Counter proposal",
        references=["<root@redliner.local>"],
        provider="test",
    )
    assert (
        repository.find_deal_by_reply(in_reply_to="<thread-1@redliner.local>")
        == "DEAL-THREAD"
    )
    assert (
        repository.find_deal_by_reply(
            references=["<root@redliner.local>", "<thread-1@redliner.local>"]
        )
        == "DEAL-THREAD"
    )
