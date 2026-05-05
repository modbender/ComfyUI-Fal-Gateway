"""Tests for fal_config: env-var → config.ini → placeholder handling."""

import os


from src.fal.config import FalConfig


PLACEHOLDER = "<your_fal_api_key_here>"


def _write_ini(path, key):
    path.write_text(f"[API]\nFAL_KEY = {key}\n", encoding="utf-8")


def test_returns_env_var_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "env-key-123")
    cfg = FalConfig(config_path=str(tmp_path / "missing.ini"))
    assert cfg.key == "env-key-123"


def test_falls_back_to_config_ini_when_env_var_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("FAL_KEY", raising=False)
    ini_path = tmp_path / "config.ini"
    _write_ini(ini_path, "ini-key-456")
    cfg = FalConfig(config_path=str(ini_path))
    assert cfg.key == "ini-key-456"


def test_env_var_takes_precedence_over_config_ini(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "env-wins")
    ini_path = tmp_path / "config.ini"
    _write_ini(ini_path, "ini-loses")
    cfg = FalConfig(config_path=str(ini_path))
    assert cfg.key == "env-wins"


def test_missing_both_sources_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("FAL_KEY", raising=False)
    cfg = FalConfig(config_path=str(tmp_path / "absent.ini"))
    assert cfg.key is None


def test_placeholder_value_in_env_treated_as_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", PLACEHOLDER)
    cfg = FalConfig(config_path=str(tmp_path / "absent.ini"))
    assert cfg.key is None


def test_placeholder_value_in_config_treated_as_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("FAL_KEY", raising=False)
    ini_path = tmp_path / "config.ini"
    _write_ini(ini_path, PLACEHOLDER)
    cfg = FalConfig(config_path=str(ini_path))
    assert cfg.key is None


def test_config_ini_value_populates_env_var_as_side_effect(monkeypatch, tmp_path):
    """fal-client reads FAL_KEY from os.environ; we propagate config.ini value to env."""
    monkeypatch.delenv("FAL_KEY", raising=False)
    ini_path = tmp_path / "config.ini"
    _write_ini(ini_path, "side-effect-key")
    FalConfig(config_path=str(ini_path))
    assert os.environ.get("FAL_KEY") == "side-effect-key"


def test_env_var_already_set_is_not_clobbered_by_config(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "original-env")
    ini_path = tmp_path / "config.ini"
    _write_ini(ini_path, "should-not-overwrite")
    FalConfig(config_path=str(ini_path))
    assert os.environ.get("FAL_KEY") == "original-env"


def test_empty_config_section_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("FAL_KEY", raising=False)
    ini_path = tmp_path / "config.ini"
    ini_path.write_text("[API]\n", encoding="utf-8")
    cfg = FalConfig(config_path=str(ini_path))
    assert cfg.key is None
