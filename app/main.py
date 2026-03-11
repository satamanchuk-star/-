"""Entry point for AlexBot."""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.handlers import help as help_handler
from app.handlers import moderation as moderation_handler
from app.handlers import quiz as quiz_handler
from app.middleware.logging_middleware import LoggingMiddleware
from app.models.base import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Telegram bot token format: <digits>:<alphanumeric+special>
_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]+$")


async def main() -> None:
    token = settings.bot_token
    if not token:
        raise SystemExit(
            "FATAL: Bot token is not set. "
            "Provide BOT_TOKEN or DOCKERHUB_TOKEN environment variable.\n"
            "  - via .env file:  BOT_TOKEN=123456:ABC-DEF...\n"
            "  - via docker-compose environment section\n"
            "  - via shell:  export BOT_TOKEN=123456:ABC-DEF..."
        )
    if not _TOKEN_RE.match(token):
        raise SystemExit(
            f"FATAL: Bot token has invalid format: '{token[:6]}...'\n"
            "Expected format: 1234567890:AABBCCdd-EEff (digits, colon, alphanumeric).\n"
            "Get a valid token from @BotFather in Telegram."
        )

    await init_db()

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # NOTE: Use RedisStorage or SQLiteStorage in production to survive restarts.
    # MemoryStorage loses FSM state on restart (known limitation).
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(LoggingMiddleware())

    # Router registration order matters — quiz before moderation to handle
    # answer messages first, then moderation catches anything that slips through.
    dp.include_router(help_handler.router)
    dp.include_router(quiz_handler.router)
    dp.include_router(moderation_handler.router)

    logger.info("AlexBot starting...")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
