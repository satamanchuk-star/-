"""Logging middleware — records incoming messages to DB / logs."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Log all incoming messages (non-blocking)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text:
            logger.debug(
                "msg chat=%s user=%s text=%r",
                getattr(event.chat, "id", None),
                getattr(getattr(event, "from_user", None), "id", None),
                event.text[:80],
            )
        # Always call the handler — do NOT swallow exceptions from it
        return await handler(event, data)
