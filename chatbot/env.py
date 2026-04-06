"""Environment-backed settings."""

import os
from pathlib import Path


def _load_dotenv_files() -> None:
    """Merge ``.env`` into ``os.environ`` (does not override existing vars).

    Looks for ``retirement_simulator/.env`` then repo-parent ``.env`` so the key is
    available when Streamlit is launched from an IDE that does not load your shell profile.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    sim_root = Path(__file__).resolve().parent.parent
    for path in (sim_root / ".env", sim_root.parent / ".env"):
        load_dotenv(path)


_load_dotenv_files()


def resolve_openai_api_key(explicit: str | None = None) -> str:
    """Sidebar/session value wins if non-empty; otherwise ``OPENAI_API_KEY``."""
    s = (explicit or "").strip()
    if s:
        return s
    return (os.environ.get("OPENAI_API_KEY") or "").strip()
