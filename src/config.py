"""Centralized configuration for Mantis.

Loads environment variables from .env once and exposes validated
settings. Never prints secret values.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from logger import get_logger

log = get_logger("config")

# Load .env from the project root (two levels up from src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class GeminiConfig:
    """Gemini LLM settings."""
    api_key: str = ""
    model: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration."""
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    # Future stages will add recon limits here:
    # request_timeout, max_redirects, max_pages, max_depth, etc.


def load_config() -> AppConfig:
    """Build and validate the application configuration from the environment.

    Missing Gemini credentials produce a warning but do not prevent
    the CLI from starting (deterministic features still work).
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "").strip()

    if not api_key:
        log.warning("GEMINI_API_KEY is not set. LLM-dependent features will be unavailable.")
    if not model:
        log.warning("GEMINI_MODEL is not set. LLM-dependent features will be unavailable.")

    return AppConfig(
        gemini=GeminiConfig(api_key=api_key, model=model),
    )


# Singleton loaded once at import time for convenience.
config = load_config()
