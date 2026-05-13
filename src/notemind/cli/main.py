"""NoteMind CLI — main entry point.

Supports both:
    notemind --source /path/to/files       (pip installed)
    python -m notemind --source /path/to/files
    python import.py --source /path/to/files  (backward compat)
"""

import argparse
import sys
from pathlib import Path

# Allow running from repo root without pip install
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from notemind import __version__


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="notemind",
        description="Convert documents (PDF, Word, PPT, Excel, images) to Obsidian Vault notes with AI-powered analysis.",
        epilog="Examples:\n"
               "  notemind --source ./inbox\n"
               "  notemind --source ./docs --vault ./knowledge-base --dry-run\n"
               "  notemind --update --source ./docs --vault ./knowledge-base\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"notemind {__version__}")
    parser.add_argument("--source", default=None, help="Path to source files directory (default: <vault>/myfiles)")
    parser.add_argument("--vault", help="Vault directory path (overrides config.json)")
    parser.add_argument("--dry-run", action="store_true", help="Preview mode — do not write files")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--migrate", action="store_true", help="Migrate existing docs to new format")
    parser.add_argument("--update", action="store_true", help="Validate and fix existing MD file categories")
    parser.add_argument("--config", help="Path to config file (default: config.json)")
    return parser


def main():
    """CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Delegate to the import pipeline
    # In Phase 2, this will call the orchestrator directly
    from importlib import import_module
    import_mod = import_module('import')
    import_mod.main_cli(args)
