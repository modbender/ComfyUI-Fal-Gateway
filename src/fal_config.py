"""FAL_KEY resolution: env var (highest precedence) → config.ini → None.

Mirrors the auth pattern from gokayfem/ComfyUI-fal-API (`fal_utils.py:13-64`)
with cleanups:
- Treat the documented placeholder string as "not set".
- When the key comes from config.ini, populate `os.environ["FAL_KEY"]` so the
  underlying fal-client picks it up automatically.
- Never overwrite an existing env var with a config.ini value.
- No singleton or module-level cache; constructing a `FalConfig` is cheap and
  testable. Production callers go through `default_config()` which builds with
  the package's own config.ini path.
"""

from __future__ import annotations

import configparser
import logging
import os
from pathlib import Path

_log = logging.getLogger("fal_gateway.config")

PLACEHOLDER = "<your_fal_api_key_here>"


def _default_config_path() -> str:
    return str(Path(__file__).resolve().parent.parent / "config.ini")


class FalConfig:
    PLACEHOLDER = PLACEHOLDER

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path: str = config_path or _default_config_path()
        self.key: str | None = self._resolve()

    def _resolve(self) -> str | None:
        env = os.environ.get("FAL_KEY")
        if env and env != self.PLACEHOLDER:
            return env

        if not os.path.exists(self.config_path):
            return None

        parser = configparser.ConfigParser()
        try:
            parser.read(self.config_path, encoding="utf-8")
        except configparser.Error as exc:
            _log.warning("could not read %s: %s", self.config_path, exc)
            return None

        try:
            value = parser["API"]["FAL_KEY"]
        except KeyError:
            return None

        if not value or value == self.PLACEHOLDER:
            return None

        # Side effect: propagate to env so fal-client reads it without our help.
        if "FAL_KEY" not in os.environ:
            os.environ["FAL_KEY"] = value
        return value

    @property
    def is_configured(self) -> bool:
        return self.key is not None


def default_config() -> FalConfig:
    """Build a FalConfig using the package-default config.ini path."""
    return FalConfig()
