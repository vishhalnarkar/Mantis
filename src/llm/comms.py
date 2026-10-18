"""LLM communication module.

Talks to Gemini through the OpenAI-compatible endpoint. The client is
created lazily so that importing this module never fails, even when
credentials are missing.
"""

from openai import OpenAI

from config import config
from logger import get_logger, console

log = get_logger("llm.comms")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
REQUEST_TIMEOUT = 30.0

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Return a configured OpenAI client, creating it on first use."""
    global _client
    if _client is None:
        if not config.gemini.is_configured:
            raise RuntimeError(
                "Gemini is not configured. Set GEMINI_API_KEY and GEMINI_MODEL "
                "in your .env file (see .env.example)."
            )
        _client = OpenAI(
            api_key=config.gemini.api_key,
            base_url=GEMINI_BASE_URL,
            timeout=REQUEST_TIMEOUT,
        )
    return _client


def send_message(messages: list) -> str:
    """Send a chat completion request to the configured LLM."""
    if not messages:
        raise ValueError("Messages cannot be empty.")

    client = _get_client()
    model = config.gemini.model

    log.info("Sending request to model: %s", model)
    log.debug("Message count: %d", len(messages))

    try:
        with console.status("[accent]Thinking...[/]", spinner="dots"):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
            )

        usage = response.usage
        if usage:
            log.info(
                "Token usage - input: %d, output: %d, total: %d",
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
            )
            console.print(
                f"[dim]Tokens used -> input: {usage.prompt_tokens} | "
                f"output: {usage.completion_tokens} | "
                f"total: {usage.total_tokens}[/]"
            )

        content = response.choices[0].message.content
        log.info("Received response from model (%d chars)", len(content) if content else 0)
        return content

    except Exception as e:
        log.exception("LLM request failed: %s", e)
        raise RuntimeError(f"LLM request failed: {e}") from e
