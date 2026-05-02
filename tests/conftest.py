"""Test-suite-wide fixtures.

Auto-loads `.env` (gitignored) at session start so integration tests have
FAL_KEY without needing to run `source .env` first. Unit tests don't need
the key — they monkeypatch or mock — but the lift is harmless for them.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env loader — no python-dotenv dependency required.

    Reads `KEY=value` lines, skips comments / blanks, doesn't override
    keys that are already set in the real environment.
    """
    repo_root = Path(__file__).resolve().parent.parent
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()
