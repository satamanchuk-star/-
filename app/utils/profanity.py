"""Utilities for loading profanity word lists from disk."""
from __future__ import annotations

import os
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_PROFANITY_FILE = _DATA_DIR / "profanity.txt"
_EXCEPTIONS_FILE = _DATA_DIR / "profanity_exceptions.txt"


def _load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    words: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line.lower())
    return words


def load_profanity() -> list[str]:
    """Return all profanity roots/words from profanity.txt."""
    return _load_lines(_PROFANITY_FILE)


def load_profanity_exceptions() -> list[str]:
    """Return all exception words that must not be flagged."""
    return _load_lines(_EXCEPTIONS_FILE)
