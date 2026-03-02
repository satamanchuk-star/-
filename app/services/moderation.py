"""Moderation pipeline — combines local rules with AI verdict.

Fix: run_moderation() now implements a proper escalation matrix:
- severity 0 → no action
- severity 1 → warn only
- severity 2 → delete message + warn
- severity 3 → mute 24 h (first offence), ban (repeat)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aiogram.exceptions import TelegramBadRequest

from app.services.ai_module import OpenRouterProvider, detect_profanity
from app.utils.text import contains_forbidden_link

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

logger = logging.getLogger(__name__)

_ai = OpenRouterProvider()

# In-memory strike counter (reset on restart; good enough for MVP)
_strike_count: dict[tuple[int, int], int] = {}  # (chat_id, user_id) -> strikes


async def run_moderation(
    message: "Message",
    bot: "Bot",
    forum_chat_id: int,
) -> bool:
    """Analyse *message* and take the appropriate moderation action.

    Returns True if an action was taken (message deleted / user muted), False
    if the message is clean.
    """
    text = message.text or message.caption or ""
    user_id = message.from_user.id if message.from_user else 0

    # --- Fast local checks ---
    has_bad_link = contains_forbidden_link(text, forum_chat_id)

    # --- AI verdict ---
    verdict: dict[str, Any] = {}
    if has_bad_link:
        verdict = {
            "violation_type": "forbidden_link",
            "severity": 2,
            "confidence": 0.9,
            "action": "delete",
        }
    else:
        # AI модерация анализирует контекст, не только отдельные слова
        try:
            verdict = await _ai.moderate_message(text, chat_id=forum_chat_id)
        except Exception as exc:
            logger.warning("Moderation AI call failed: %s", exc)
            return False

    severity = int(verdict.get("severity", 0))
    if severity == 0:
        return False

    key = (forum_chat_id, user_id)
    strikes = _strike_count.get(key, 0)

    try:
        if severity == 1:
            # Warn only — do NOT delete
            await message.reply("⚠️ Пожалуйста, соблюдайте правила чата.")

        elif severity == 2:
            # Delete + warn
            await message.delete()
            await bot.send_message(
                forum_chat_id,
                f"⚠️ Сообщение пользователя было удалено за нарушение правил.",
                message_thread_id=message.message_thread_id,
            )

        elif severity >= 3:
            await message.delete()
            if strikes == 0:
                # First offence → mute 24 h
                from datetime import timedelta
                await bot.restrict_chat_member(
                    forum_chat_id,
                    user_id,
                    permissions=_no_permissions(),
                    until_date=timedelta(hours=24),
                )
                await bot.send_message(
                    forum_chat_id,
                    "🔇 Пользователь заблокирован на 24 часа за грубое нарушение.",
                    message_thread_id=message.message_thread_id,
                )
            else:
                # Repeat offence → ban
                await bot.ban_chat_member(forum_chat_id, user_id)
                await bot.send_message(
                    forum_chat_id,
                    "🚫 Пользователь забанен за повторное нарушение.",
                    message_thread_id=message.message_thread_id,
                )
            _strike_count[key] = strikes + 1

    except TelegramBadRequest as exc:
        logger.warning("Moderation action failed: %s", exc)
        return False

    return severity > 0


def _no_permissions():
    from aiogram.types import ChatPermissions
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
    )
