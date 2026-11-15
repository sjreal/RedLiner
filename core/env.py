"""Load the repository-local .env before application settings are read."""

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_app_env() -> None:
    """Idempotently load project environment settings without overriding shell vars."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)


load_app_env()
