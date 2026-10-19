"""Tests for src/llm/comms.py using mocks. No live API calls."""

import pytest


def test_send_message_empty_raises():
    import llm.comms as comms
    with pytest.raises(ValueError, match="Messages cannot be empty"):
        comms.send_message([])


def test_send_message_unconfigured_raises(monkeypatch):
    import llm.comms as comms
    # Force unconfigured state
    monkeypatch.setattr(comms, "_client", None)
    from config import GeminiConfig, AppConfig
    monkeypatch.setattr(comms, "config", AppConfig(gemini=GeminiConfig()))
    with pytest.raises(RuntimeError, match="Gemini is not configured"):
        comms.send_message([{"role": "user", "content": "hi"}])


def test_send_message_success_with_mock(monkeypatch):
    import llm.comms as comms

    class FakeUsage:
        prompt_tokens = 5
        completion_tokens = 3
        total_tokens = 8

    class FakeMessage:
        content = "mocked reply"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        usage = FakeUsage()
        choices = [FakeChoice()]

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return FakeResponse()

    from config import GeminiConfig, AppConfig
    monkeypatch.setattr(comms, "_client", FakeClient())
    monkeypatch.setattr(comms, "config", AppConfig(gemini=GeminiConfig(api_key="k", model="m")))

    result = comms.send_message([{"role": "user", "content": "hi"}])
    assert result == "mocked reply"
