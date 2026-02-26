"""Admin-check utilities with TTL caching.

Fix (Task 6): Previously is_admin() made a live Telegram API call on EVERY
message, which causes rate-limit problems at 100+ msg/min. Now results are
cached for ADMIN_CACHE_TTL_MIN minutes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from aiogram import Bot

# (chat_id, user_id) -> (is_admin_result, cached_at)
_ADMIN_CACHE: dict[tuple[int, int], tuple[bool, datetime]] = {}


def _cache_ttl() -> timedelta:
    return timedelta(minutes=settings.admin_cache_ttl_min)


async def is_admin(bot: "Bot", chat_id: int, user_id: int) -> bool:
    """Return True if *user_id* is an admin/creator in *chat_id*.

    Results are cached for ``settings.admin_cache_ttl_min`` minutes to avoid
    hammering the Telegram API.
    """
    key = (chat_id, user_id)
    now = datetime.now(timezone.utc)

    if key in _ADMIN_CACHE:
        result, cached_at = _ADMIN_CACHE[key]
        if now - cached_at < _cache_ttl():
            return result

    member = await bot.get_chat_member(chat_id, user_id)
    result = member.status in {"administrator", "creator"}
    _ADMIN_CACHE[key] = (result, now)
    return result


def invalidate_admin_cache(chat_id: int, user_id: int) -> None:
    """Remove a single entry from the admin cache.

    Call this after /mute, /ban, /unban so the next check fetches fresh data.
    """
    _ADMIN_CACHE.pop((chat_id, user_id), None)


def clear_admin_cache() -> None:
    """Flush the entire admin cache (useful in tests)."""
    _ADMIN_CACHE.clear()
