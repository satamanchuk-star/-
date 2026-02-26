"""Shared pytest fixtures."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="alexbot", id=123456))
    bot.get_chat_member = AsyncMock(
        return_value=MagicMock(status="member")
    )
    return bot
