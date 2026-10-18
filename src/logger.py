import sys
import logging
from rich.console import Console
from rich.theme import Theme
from rich.logging import RichHandler

# Force UTF-8 on Windows so emojis/special chars don't crash cp1252
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.platform == "win32" and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Custom color theme for Mantis CLI
MANTIS_THEME = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "accent": "bold magenta",
    "dim": "dim",
})

console = Console(theme=MANTIS_THEME)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that outputs color-coded logs to the terminal."""
    logger = logging.getLogger(f"mantis.{name}")
    if not logger.handlers:
        handler = RichHandler(
            console=Console(stderr=True, theme=MANTIS_THEME),
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger
