"""Purge old deal history and optional generated artifacts."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from core.store_factory import get_deal_repository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("RETENTION_DAYS", "90")),
    )
    parser.add_argument("--artifacts", action="store_true")
    args = parser.parse_args()

    repository = get_deal_repository()
    result = repository.purge(args.days)
    print(f"Purged records older than {args.days} days: {result}")

    if args.artifacts:
        cutoff = time.time() - max(0, args.days) * 86400
        removed = 0
        for path in Path("data/outputs").glob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        print(f"Removed {removed} old generated artifacts")


if __name__ == "__main__":
    main()
