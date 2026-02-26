"""Entry point for AlexBot."""
from __future__ import annotations

import asyncio
import logging

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


async def main() -> None:
    await init_db()

    bot = Bot(
        token=settings.bot_token,
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
    if not settings.bot_token:
        logger.critical(
            "BOT_TOKEN is not set. "
            "Copy .env.example to .env and fill in your Telegram bot token."
        )
        raise SystemExit(1)
    asyncio.run(main())
