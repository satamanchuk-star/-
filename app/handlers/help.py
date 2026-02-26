"""Help and assistant dialog handlers.

Fixes applied:
- Task 3: _is_bot_name_called() regex fixed — was rf'(?<!\\w)...' (double
          escape → literal \\w). Now uses correct word-boundary raw strings.
- Task 4: assistant_reply() logic for greetings and off-topic already fixed
          in ai_module.py; this handler just routes to it.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.services.ai_module import OpenRouterProvider
from app.utils.admin import is_admin

if TYPE_CHECKING:
    pass

router = Router(name="help")
logger = logging.getLogger(__name__)

_ai = OpenRouterProvider()

# Bot name variants the assistant responds to
_BOT_NAMES = ["alexbot", "алексбот", "алекс бот", "бот"]


def _is_bot_name_called(text: str, bot_names: list[str] | None = None) -> bool:
    """Return True if any bot name is mentioned in *text*.

    Fix (Task 3): The original code had:
        pattern = rf"(?<!\\w){re.escape(name.casefold())}(?!\\w)"
    In Python, inside an rf-string, \\w is a literal backslash + w, NOT a
    regex word character. The lookbehind/lookahead therefore never matched.

    Correct fix: build the boundary pattern from a plain raw string:
        r"(?<![\w])" + ... + r"(?![\w])"
    """
    names = bot_names if bot_names is not None else _BOT_NAMES
    text_lower = text.lower()
    for name in names:
        # Correct word-boundary pattern (Task 3 fix)
        pattern = r"(?<![\w])" + re.escape(name.casefold()) + r"(?![\w])"
        if re.search(pattern, text_lower):
            return True
    return False


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show help menu with links to forum topics."""
    forum_id = settings.forum_chat_id
    # Build numeric prefix for t.me/c/ links (strips -100 prefix)
    cid = str(abs(forum_id))
    num = cid[3:] if cid.startswith("100") else cid

    text = (
        "📖 <b>Добро пожаловать в AlexBot!</b>\n\n"
        "Я помогу с вопросами о ЖК:\n"
        "• <b>Шлагбаум</b> — правила въезда\n"
        "• <b>Правила чата</b> — что разрешено\n"
        "• <b>Соседи</b> — как решить конфликт\n\n"
        "Можете обратиться ко мне напрямую — просто упомяните моё имя!\n\n"
        f"🔗 <a href='https://t.me/c/{num}/{settings.topic_rules}'>Правила чата</a>\n"
        f"🔗 <a href='https://t.me/c/{num}/{settings.topic_gate}'>Шлагбаум</a>"
    )
    await message.reply(text, parse_mode="HTML")


@router.message(F.text)
async def handle_mention(message: Message, bot: Bot) -> None:
    """Respond when the bot is mentioned by name in a message."""
    if not message.text:
        return

    # Only respond in the forum
    if message.chat.id != settings.forum_chat_id:
        return

    bot_info = await bot.get_me()
    names = _BOT_NAMES.copy()
    if bot_info.username:
        names.append(bot_info.username.lower())

    if not _is_bot_name_called(message.text, names):
        return

    # Strip the bot name from the prompt
    prompt = message.text
    for name in names:
        prompt = re.sub(
            r"(?<![\w])" + re.escape(name) + r"(?![\w])",
            "",
            prompt,
            flags=re.IGNORECASE,
        )
    prompt = prompt.strip(" ,!?")

    reply = await _ai.assistant_reply(
        prompt or "привет",
        chat_id=message.chat.id,
    )
    await message.reply(reply)


@router.message(Command("reload_profanity"))
async def cmd_reload_profanity(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        return
    from app.services.ai_module import reload_profanity_dicts
    count = reload_profanity_dicts()
    await message.reply(f"✅ Словарь мата перезагружен: {count} корней.")


@router.message(Command("updaterag"))
async def cmd_update_rag(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        return
    from app.services.rag import load_rag_from_telegram
    count = await load_rag_from_telegram(bot)
    await message.reply(f"✅ RAG обновлён: {count} фрагментов загружено.")
