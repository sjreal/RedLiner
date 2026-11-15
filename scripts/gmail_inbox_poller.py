"""Poll a Gmail inbox over IMAP and process contract attachments.

This is the no-domain alternative to Cloudflare Email Routing. It uses the
same Gmail App Password as Direct SMTP. It only drafts replies; it never sends
automatically.

Usage:
    PYTHONPATH=. uv run python scripts/gmail_inbox_poller.py --once
    PYTHONPATH=. uv run python scripts/gmail_inbox_poller.py --interval 60
"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import re
import time
from datetime import datetime, timezone
from email import policy
from email.utils import parseaddr
from pathlib import Path

from agents.orchestrator import MainOrchestrator
from core.env import load_app_env
from core.email_config import get_email_credentials

load_app_env()

BASE_DIR = Path(__file__).resolve().parent.parent
INCOMING_DIR = BASE_DIR / "data" / "incoming"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"
RUN_LOG = INCOMING_DIR / "gmail_poller_runs.jsonl"
SUPPORTED_SUFFIXES = {".docx", ".pdf"}


def _safe_name(value: str, fallback: str = "contract") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or fallback


def _message_text(message: email.message.EmailMessage) -> str:
    if not message.is_multipart():
        payload = message.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if payload else ""
    parts = []
    for part in message.walk():
        if part.get_content_type() != "text/plain":
            continue
        if "attachment" in (part.get("Content-Disposition") or "").lower():
            continue
        payload = part.get_payload(decode=True)
        if payload:
            parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _attachments(message: email.message.EmailMessage) -> list[tuple[str, bytes]]:
    found = []
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            found.append((Path(filename).name, payload))
    return found


def _append_run(record: dict) -> None:
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, default=str) + "\n")


def _process_message(
    imap: imaplib.IMAP4_SSL,
    uid: bytes,
    orchestrator: MainOrchestrator,
    mark_skipped_seen: bool,
) -> None:
    status, response = imap.uid("fetch", uid, "(RFC822)")
    if status != "OK":
        print(f"[gmail-poller] Could not fetch UID {uid!r}: {status}")
        return

    raw = next(
        (item[1] for item in response if isinstance(item, tuple) and len(item) > 1),
        None,
    )
    if raw is None:
        print(f"[gmail-poller] Empty message for UID {uid!r}")
        return

    message = email.message_from_bytes(raw, policy=policy.default)
    sender_email = parseaddr(message.get("From", ""))[1] or "unknown@example.com"
    sender_name = parseaddr(message.get("From", ""))[0] or sender_email
    subject = str(message.get("Subject", "")).strip()
    message_id = str(message.get("Message-ID", "")).strip()
    deal_id = f"GMAIL-{_safe_name((message_id or uid.decode())[:32], 'deal')}"
    attachments = _attachments(message)

    in_reply_to = str(message.get("In-Reply-To", "")).strip() or None
    references = [
        value.strip()
        for value in str(message.get("References", "")).split()
        if value.strip()
    ]
    deal_reference = str(message.get("X-RedLiner-Deal", "")).strip() or None
    matched_deal = orchestrator.find_deal_for_reply(
        in_reply_to=in_reply_to,
        references=references,
        deal_reference=deal_reference,
    )

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uid": uid.decode(),
        "message_id": message_id,
        "from": sender_email,
        "subject": subject,
        "attachments": [name for name, _ in attachments],
        "in_reply_to": in_reply_to,
        "references": references,
        "matched_deal": matched_deal,
    }

    if matched_deal:
        reply_text = f"{subject}\n{_message_text(message)}"[:100000]
        try:
            state = orchestrator.handle_vendor_reply(
                matched_deal,
                reply_text,
                subject=subject,
            )
            record.update(
                {
                    "status": "COUNTEROFFER_APPLIED"
                    if state.counteroffer.get("status") == "APPLIED"
                    else "COUNTEROFFER_NEEDS_REVIEW",
                    "iteration": state.iteration,
                    "run_status": state.run_status,
                    "convergence_reason": state.convergence_reason,
                    "counteroffer": state.counteroffer,
                }
            )
            print(
                f"[gmail-poller] Matched reply to {matched_deal}: "
                f"{state.run_status}"
            )
        except Exception as exc:
            record.update({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
            print(f"[gmail-poller] Reply error for UID {uid.decode()}: {exc}")
        finally:
            _append_run(record)
            imap.uid("store", uid, "+FLAGS", "\\Seen")
        return

    if not attachments:
        record.update({"status": "SKIPPED_NO_SUPPORTED_ATTACHMENT"})
        _append_run(record)
        if mark_skipped_seen:
            imap.uid("store", uid, "+FLAGS", "\\Seen")
        print(f"[gmail-poller] Skipped UID {uid.decode()}: no .docx/.pdf attachment")
        return

    filename, content = attachments[0]
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = INCOMING_DIR / f"{deal_id}_{_safe_name(filename)}"
    saved_path.write_bytes(content)

    try:
        state = orchestrator.process_incoming_deal(
            deal_id=deal_id,
            contract_path=saved_path,
            vendor_name=sender_name,
            output_dir=OUTPUT_DIR,
            email_context=f"{subject}\n{_message_text(message)}"[:100000],
        )
        record.update(
            {
                "status": state.run_status,
                "violations_detected": len(state.redline_actions),
                "requires_human_approval": state.requires_human_approval,
                "llm_status": state.llm_status,
                "redlined_docx_filename": (
                    state.redline_result.output_docx_filename
                    if state.redline_result
                    else None
                ),
                "trace_id": state.trace_id,
            }
        )
        print(
            "[gmail-poller] Processed "
            f"{sender_email} / {filename}: {state.run_status}, "
            f"{len(state.redline_actions)} redlines, llm={state.llm_status}"
        )
    except Exception as exc:
        record.update({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
        print(f"[gmail-poller] Error for UID {uid.decode()}: {type(exc).__name__}: {exc}")
    finally:
        _append_run(record)
        # Mark seen so a malformed attachment cannot be processed endlessly.
        imap.uid("store", uid, "+FLAGS", "\\Seen")


def poll_once(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    limit: int,
    mark_skipped_seen: bool,
) -> int:
    imap = imaplib.IMAP4_SSL(host, port)
    try:
        imap.login(user, password)
        status, _ = imap.select(folder, readonly=False)
        if status != "OK":
            raise RuntimeError(
                f"Could not select folder {folder!r}: {status}. "
                "In Gmail Settings > Labels, enable 'Show in IMAP' for that label "
                "and apply it to at least one message. Otherwise use "
                "--folder INBOX for a diagnostic run."
            )
        status, data = imap.uid("search", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")
        uids = data[0].split()[:limit] if data and data[0] else []
        if not uids:
            print("[gmail-poller] No unread messages.")
            return 0
        orchestrator = MainOrchestrator()
        for uid in uids:
            _process_message(
                imap,
                uid,
                orchestrator,
                mark_skipped_seen=mark_skipped_seen,
            )
        return len(uids)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Poll once and exit.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between polls.")
    parser.add_argument(
        "--folder",
        default="RedLiner",
        help="Gmail label to poll; use INBOX only if you accept the risk.",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--mark-skipped-seen", action="store_true")
    parser.add_argument("--host", default="imap.gmail.com")
    parser.add_argument("--port", type=int, default=993)
    args = parser.parse_args()
    if args.folder.upper() == "INBOX":
        print(
            "[gmail-poller] WARNING: polling INBOX may process unread personal mail "
            "with .docx/.pdf attachments. Prefer a dedicated Gmail label."
        )

    credentials = get_email_credentials()
    user = credentials.get("smtp_user", "")
    password = credentials.get("smtp_password", "")
    if not user or not password:
        raise SystemExit(
            "SMTP_USER / SMTP_PASSWORD are missing. Configure Direct SMTP in the "
            "dashboard or set them in the project .env."
        )

    while True:
        try:
            poll_once(
                host=args.host,
                port=args.port,
                user=user,
                password=password,
                folder=args.folder,
                limit=args.limit,
                mark_skipped_seen=args.mark_skipped_seen,
            )
        except KeyboardInterrupt:
            print("\n[gmail-poller] Stopped.")
            return
        except Exception as exc:
            print(f"[gmail-poller] Poll failed: {type(exc).__name__}: {exc}")
        if args.once:
            return
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    main()
