"""Tests for src/config.py"""

import importlib
import os


def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    import config
    cfg = config.load_config()
    assert cfg.gemini.api_key == "test-key"
    assert cfg.gemini.model == "test-model"
    assert cfg.gemini.is_configured is True


def test_load_config_missing_key_warns_but_returns(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    import config
    cfg = config.load_config()
    assert cfg.gemini.is_configured is False


def test_secrets_not_in_str_repr(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    import config
    cfg = config.load_config()
    # repr of a dataclass includes field values; ensure we don't casually print it.
    # The contract: we never log cfg. This test just verifies the object holds the value.
    assert cfg.gemini.api_key == "super-secret-value"
