"""Run the Gmail IMAP poller inside the hosted backend process.

This is the no-domain demo path: no local terminal, no Cloudflare Email Routing,
and no separate worker service. Run exactly one backend instance.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from core.email_config import get_email_credentials


class GmailPollerWorker(threading.Thread):
    def __init__(self, interval: int = 60, folder: str = "RedLiner", limit: int = 10):
        super().__init__(name="redliner-gmail-poller", daemon=True)
        self.interval = max(5, interval)
        self.folder = folder
        self.limit = limit
        self.stop_event = threading.Event()

    def run(self) -> None:
        from scripts.gmail_inbox_poller import poll_once

        credentials = get_email_credentials()
        user = credentials.get("smtp_user", "")
        password = credentials.get("smtp_password", "")
        if not user or not password:
            print("[inbox-worker] Gmail credentials missing; poller disabled")
            return

        print(f"[inbox-worker] polling Gmail label {self.folder!r} every {self.interval}s")
        while not self.stop_event.is_set():
            try:
                poll_once(
                    host="imap.gmail.com",
                    port=993,
                    user=user,
                    password=password,
                    folder=self.folder,
                    limit=self.limit,
                    mark_skipped_seen=False,
                )
            except Exception as exc:
                print(f"[inbox-worker] poll failed: {type(exc).__name__}: {exc}")
            self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()


_worker: Optional[GmailPollerWorker] = None


def start_worker_from_env() -> Optional[GmailPollerWorker]:
    global _worker
    if _worker is not None:
        return _worker
    if os.environ.get("GMAIL_POLL_ENABLED", "false").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    _worker = GmailPollerWorker(
        interval=int(os.environ.get("GMAIL_POLL_INTERVAL", "60")),
        folder=os.environ.get("GMAIL_POLL_FOLDER", "RedLiner"),
        limit=int(os.environ.get("GMAIL_POLL_LIMIT", "10")),
    )
    _worker.start()
    return _worker


def stop_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None
