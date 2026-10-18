"""Bounded, mockable chat session service (Stage 09).

Wraps the existing LLM client (llm.comms) behind a small interface that
tests can mock. Design guarantees:

- History is bounded by turn count AND total character budget.
- History is in-memory only; never persisted by default.
- ask() never raises; failures return a structured ChatTurnResult.
- Failed turns never corrupt or partially mutate history.
- Empty and oversized user input are rejected before any model call.
- Empty model responses are treated as malformed, not stored.
- Error messages are sanitized; a configured secret is redacted.
- This module never imports recon, storage, reporting, or target code.
"""

from __future__ import annotations

from dataclasses import dataclass

from logger import get_logger

log = get_logger("chatbot")

# ── Bounds ──────────────────────────────────────────────────────────────
MAX_HISTORY_TURNS = 20          # user+assistant pairs kept (plus system msg)
MAX_USER_INPUT_CHARS = 8_000    # per-message input cap
MAX_HISTORY_CHARS = 60_000      # total character budget for context

# ── Error kinds ─────────────────────────────────────────────────────────
ERR_CONFIG = "config"
ERR_INPUT_EMPTY = "input-empty"
ERR_INPUT_TOO_LONG = "input-too-long"
ERR_TIMEOUT = "timeout"
ERR_RATE_LIMIT = "rate-limit"
ERR_AUTH = "auth"
ERR_NETWORK = "network"
ERR_MALFORMED = "malformed-response"
ERR_UNKNOWN = "unknown"


@dataclass
class ChatTurnResult:
    """Structured outcome of one chat turn. Never raises."""
    ok: bool
    reply: str = ""
    error: str = ""
    error_kind: str = ""


def _default_send(messages: list) -> str:
    """Default LLM call via the shared client (lazy import keeps the
    chatbot importable even if openai is missing)."""
    from llm.comms import send_message
    return send_message(messages)


def _classify_error(exc: Exception) -> str:
    """Map an LLM exception to a stable error kind.

    Order matters: auth/quota/timeout checks come before the config
    check so messages like '401 Unauthorized bad api key' are not
    mislabeled as configuration problems.
    """
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return ERR_TIMEOUT
    if "quota" in text or "rate" in text or "429" in text:
        return ERR_RATE_LIMIT
    if "401" in text or "403" in text or "unauthorized" in text or "permission" in text:
        return ERR_AUTH
    if "not configured" in text:
        return ERR_CONFIG
    if "connection" in text or "network" in text or "resolve" in text:
        return ERR_NETWORK
    return ERR_UNKNOWN


class ChatSession:
    """One bounded, in-memory chatbot conversation."""

    def __init__(self, system_prompt: str, send_fn=None):
        """
        Args:
            system_prompt: The versioned system prompt (always sent first).
            send_fn: Injectable callable(messages) -> str. Defaults to the
                shared llm.comms.send_message. Tests inject a mock.
        """
        self._system_prompt = system_prompt
        self._send = send_fn or _default_send
        self._turns: list[dict] = []  # alternating user/assistant pairs
        self._redact_secret = ""

    # ── secret redaction ────────────────────────────────────────────────
    def set_redact_secret(self, secret: str) -> None:
        """Register a secret string to strip from any error message."""
        self._redact_secret = secret or ""

    def _safe_error(self, exc: Exception) -> str:
        text = str(exc)[:500]
        if self._redact_secret and self._redact_secret in text:
            text = text.replace(self._redact_secret, "[REDACTED]")
        return text

    # ── state ───────────────────────────────────────────────────────────
    @property
    def turn_count(self) -> int:
        """Number of successful user turns currently in history."""
        return sum(1 for m in self._turns if m["role"] == "user")

    @property
    def messages(self) -> list[dict]:
        """Full message list as sent to the model (system first)."""
        return [{"role": "system", "content": self._system_prompt}] + list(self._turns)

    def clear(self) -> None:
        """Forget the conversation so far. System prompt is retained."""
        self._turns.clear()

    # ── history trimming ────────────────────────────────────────────────
    def _trim(self) -> None:
        # Turn-count bound: drop oldest complete pairs.
        max_msgs = MAX_HISTORY_TURNS * 2
        while len(self._turns) > max_msgs:
            self._turns.pop(0)
            if self._turns and self._turns[0]["role"] == "assistant":
                self._turns.pop(0)
        # Character budget: drop oldest complete pairs.
        total = len(self._system_prompt) + sum(len(m["content"]) for m in self._turns)
        while total > MAX_HISTORY_CHARS and len(self._turns) >= 2:
            pair_chars = len(self._turns[0]["content"]) + len(self._turns[1]["content"])
            self._turns = self._turns[2:]
            total -= pair_chars

    # ── main entry point ────────────────────────────────────────────────
    def ask(self, user_text: str) -> ChatTurnResult:
        """Send one user message and return a structured result.

        Never raises. On failure the history is unchanged so the user can
        retry cleanly.
        """
        text = (user_text or "").strip()

        if not text:
            return ChatTurnResult(
                ok=False, error="Empty message.", error_kind=ERR_INPUT_EMPTY
            )
        if len(text) > MAX_USER_INPUT_CHARS:
            return ChatTurnResult(
                ok=False,
                error=(
                    f"Message too long ({len(text)} chars, max "
                    f"{MAX_USER_INPUT_CHARS}). Please shorten it."
                ),
                error_kind=ERR_INPUT_TOO_LONG,
            )

        messages = self.messages + [{"role": "user", "content": text}]

        try:
            reply = self._send(messages)
        except Exception as e:
            kind = _classify_error(e)
            msg = self._safe_error(e)
            log.warning("Chat LLM call failed (%s): %s", kind, msg)
            return ChatTurnResult(ok=False, error=msg, error_kind=kind)

        if not reply or not str(reply).strip():
            log.warning("Chat model returned an empty response.")
            return ChatTurnResult(
                ok=False,
                error="Model returned an empty response.",
                error_kind=ERR_MALFORMED,
            )

        reply = str(reply).strip()
        self._turns.append({"role": "user", "content": text})
        self._turns.append({"role": "assistant", "content": reply})
        self._trim()
        return ChatTurnResult(ok=True, reply=reply)
