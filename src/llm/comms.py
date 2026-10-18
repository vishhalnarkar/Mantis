import os

from dotenv import load_dotenv
from openai import OpenAI

from logger import get_logger, console

load_dotenv()

log = get_logger("llm.comms")

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL")

client = OpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=30.0,
)


def send_message(messages: list) -> str:
    """Send a chat completion request to the configured LLM."""
    if not messages:
        raise ValueError("Messages cannot be empty.")

    log.info("Sending request to model: %s", MODEL)
    log.debug("Message count: %d", len(messages))

    try:
        with console.status("[accent]Thinking...[/]", spinner="dots"):
            response = client.chat.completions.create(
                model=MODEL,
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