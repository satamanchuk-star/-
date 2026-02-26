"""Text analysis and link detection utilities."""
from __future__ import annotations

import re
from typing import Sequence


# Matches http(s)/www URLs and bare t.me links
LINK_PATTERN = re.compile(
    r"(?:https?://|www\.)"
    r"[\w\-]+"
    r"(?:\.[\w\-]+)+"
    r"(?:/[^\s]*)?"
    r"|t\.me/[^\s]+",
    re.IGNORECASE,
)


def _forum_link_prefix(forum_chat_id: int) -> str:
    """Build the t.me/c/XXXXX/ prefix for the bot's own forum."""
    cid = str(abs(forum_chat_id))
    # Telegram supergroup IDs start with -100, the numeric part starts with 100
    numeric = cid[3:] if cid.startswith("100") else cid
    return f"t.me/c/{numeric}/"


def contains_forbidden_link(text: str, forum_chat_id: int = 0) -> bool:
    """Return True if *text* contains an external (non-forum) link.

    Links pointing to the bot's own forum topics are always allowed.

    Fix (Task 5): Previously ALL t.me/ links were blocked, including
    legitimate /help links to forum topics. Now internal forum links pass.
    """
    matches = LINK_PATTERN.findall(text)
    if not matches:
        return False

    allowed_prefix = _forum_link_prefix(forum_chat_id) if forum_chat_id else None

    for match in matches:
        match_lower = match.lower()
        if allowed_prefix:
            # Strip protocol prefix so both 'https://t.me/c/...' and 't.me/c/...' match
            stripped = re.sub(r"^https?://", "", match_lower)
            if stripped.startswith(allowed_prefix):
                # Link to own forum topic — OK
                continue
        return True
    return False


# ---------------------------------------------------------------------------
# Profanity helpers used by ai_module.detect_profanity()
# ---------------------------------------------------------------------------

def split_profanity_words(text: str) -> list[str]:
    """Tokenise text into lowercase words (letters only)."""
    return re.findall(r"[а-яёa-z]+", text.lower())


def contains_profanity(
    words: Sequence[str],
    profanity_roots: Sequence[str],
    exceptions: Sequence[str],
) -> bool:
    """Return True if any word matches a profanity root and is not an exception.

    Matching is bidirectional:
    - ``word.startswith(root)`` — word begins with the root (e.g. 'хуйня' matches 'хуй')
    - ``root.startswith(word) and len(word) >= 4`` — word is a truncated translit form
      (e.g. normalized 'бляд' matches stored root 'блядь')
    """
    exc_set = set(exceptions)
    for word in words:
        if word in exc_set:
            continue
        for root in profanity_roots:
            if word.startswith(root):
                return True
            # Reverse: translit may produce an incomplete form of the stored root
            if len(word) >= 4 and root.startswith(word):
                return True
    return False
