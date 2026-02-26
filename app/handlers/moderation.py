"""Moderation router — handles message events in the forum."""
from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.services.moderation import run_moderation
from app.utils.admin import invalidate_admin_cache, is_admin

router = Router(name="moderation")
logger = logging.getLogger(__name__)


@router.message()
async def moderate_incoming(message: Message, bot: Bot) -> None:
    """Auto-moderate every incoming message in the forum chat."""
    if message.chat.id != settings.forum_chat_id:
        return

    user_id = message.from_user.id if message.from_user else 0
    if not user_id:
        return

    # Skip moderation for admins
    if await is_admin(bot, settings.forum_chat_id, user_id):
        return

    await run_moderation(message, bot, settings.forum_chat_id)


@router.message(Command("mute"))
async def cmd_mute(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        return
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.reply("Ответьте на сообщение пользователя, которого хотите замутить.")
        return
    target_id = reply.from_user.id
    await bot.restrict_chat_member(
        settings.forum_chat_id,
        target_id,
        permissions=_silent_permissions(),
        until_date=3600,
    )
    invalidate_admin_cache(settings.forum_chat_id, target_id)
    await message.reply(f"🔇 Пользователь заглушён на 1 час.")


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        return
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.reply("Ответьте на сообщение пользователя, которого хотите забанить.")
        return
    target_id = reply.from_user.id
    await bot.ban_chat_member(settings.forum_chat_id, target_id)
    invalidate_admin_cache(settings.forum_chat_id, target_id)
    await message.reply("🚫 Пользователь забанен.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        return
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.reply("Ответьте на сообщение пользователя, которого хотите разбанить.")
        return
    target_id = reply.from_user.id
    await bot.unban_chat_member(settings.forum_chat_id, target_id, only_if_banned=True)
    invalidate_admin_cache(settings.forum_chat_id, target_id)
    await message.reply("✅ Пользователь разбанен.")


def _silent_permissions():
    from aiogram.types import ChatPermissions
    return ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
    )
