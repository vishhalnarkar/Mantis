"""Entry point for running Mantis as a module:

    python -m src
    (from the project root, with src on the path)

Or directly:
    python src/__main__.py
"""

import sys
import os

# Ensure src/ is importable when invoked directly
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from cli import cli

if __name__ == "__main__":
    cli()
