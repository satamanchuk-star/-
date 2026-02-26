"""Tests for moderation logic.

Covers Task 2 (profanity detection), Task 5 (link filter), Task 6 (admin cache).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_module import detect_profanity, normalize_for_profanity
from app.utils.text import contains_forbidden_link
from app.utils.admin import clear_admin_cache, is_admin


# ---------------------------------------------------------------------------
# Profanity detection (Task 2)
# ---------------------------------------------------------------------------

class TestDetectProfanity:
    def test_plain_russian_profanity(self):
        assert detect_profanity("хуй") is True

    def test_plain_russian_profanity_in_sentence(self):
        assert detect_profanity("это полный пиздец вообще") is True

    def test_masked_profanity_latin(self):
        """Task 2: Latin substitutions should be caught via transliteration."""
        assert detect_profanity("xуй") is True   # mixed latin x + cyrillic
        assert detect_profanity("xuy") is True    # full latin translit

    def test_masked_profanity_digits(self):
        """Task 2: Digit substitutions (pi3da → пизда)."""
        # '3' normalizes to 'з', 'pi' → 'пи', so 'pi3da' → 'пизда'
        assert detect_profanity("pi3da") is True

    def test_exception_words_not_flagged(self):
        """Task 2: Exception words must never be flagged."""
        assert detect_profanity("хлеб") is False
        assert detect_profanity("тебя") is False
        assert detect_profanity("бляха-муха") is False
        assert detect_profanity("сукно") is False
        assert detect_profanity("рыбак") is False

    def test_clean_text(self):
        assert detect_profanity("Добрый день, соседи!") is False
        assert detect_profanity("Когда починят лифт?") is False
        assert detect_profanity("") is False

    def test_leet_speak_bly(self):
        """bly transliterates to бл → catches блядь root."""
        assert detect_profanity("blyad") is True

    def test_leet_speak_mud(self):
        """mud transliterates to муд → catches мудак root."""
        assert detect_profanity("mudak") is True


class TestNormalizeForProfanity:
    def test_latin_to_cyrillic_basic(self):
        result = normalize_for_profanity("a")
        assert result == "а"

    def test_translit_pizd(self):
        result = normalize_for_profanity("pizda")
        assert "пизд" in result

    def test_translit_xuy(self):
        result = normalize_for_profanity("xuy")
        assert "хуй" in result

    def test_digit_substitution(self):
        result = normalize_for_profanity("и1от")  # '1' → 'и'
        assert "1" not in result

    def test_yo_normalization(self):
        # After normalization, ё-words should be searchable without ё
        result = normalize_for_profanity("ёбаный")
        assert "е" in result  # ё→е


# ---------------------------------------------------------------------------
# Link filter (Task 5)
# ---------------------------------------------------------------------------

class TestContainsForbiddenLink:
    FORUM_CHAT_ID = -1001234567890  # -100 + 1234567890

    def test_external_link_blocked(self):
        assert contains_forbidden_link("купи тут https://spam.com/buy", self.FORUM_CHAT_ID) is True

    def test_external_tme_link_blocked(self):
        assert contains_forbidden_link("вступай t.me/somechannel", self.FORUM_CHAT_ID) is True

    def test_own_forum_link_allowed(self):
        """Task 5: Internal t.me/c/FORUM_ID/ links must NOT be blocked."""
        # Forum chat id -1001234567890 → numeric part 1234567890
        own_link = "t.me/c/1234567890/42"
        assert contains_forbidden_link(own_link, self.FORUM_CHAT_ID) is False

    def test_own_forum_link_with_https_allowed(self):
        own_link = "https://t.me/c/1234567890/99"
        assert contains_forbidden_link(own_link, self.FORUM_CHAT_ID) is False

    def test_no_link(self):
        assert contains_forbidden_link("Привет соседи, как дела?", self.FORUM_CHAT_ID) is False

    def test_empty_string(self):
        assert contains_forbidden_link("", self.FORUM_CHAT_ID) is False


# ---------------------------------------------------------------------------
# Admin cache (Task 6)
# ---------------------------------------------------------------------------

class TestAdminCache:
    @pytest.mark.asyncio
    async def test_admin_result_cached(self):
        clear_admin_cache()
        bot = AsyncMock()
        bot.get_chat_member = AsyncMock(
            return_value=MagicMock(status="administrator")
        )
        result1 = await is_admin(bot, -100100, 42)
        result2 = await is_admin(bot, -100100, 42)

        assert result1 is True
        assert result2 is True
        # Should only call the API once
        assert bot.get_chat_member.call_count == 1

    @pytest.mark.asyncio
    async def test_non_admin_result_cached(self):
        clear_admin_cache()
        bot = AsyncMock()
        bot.get_chat_member = AsyncMock(
            return_value=MagicMock(status="member")
        )
        result1 = await is_admin(bot, -100100, 99)
        result2 = await is_admin(bot, -100100, 99)

        assert result1 is False
        assert result2 is False
        assert bot.get_chat_member.call_count == 1

    @pytest.mark.asyncio
    async def test_admin_message_not_moderated(self):
        """Admins should skip moderation entirely."""
        from app.utils.admin import is_admin as _is_admin
        clear_admin_cache()
        bot = AsyncMock()
        bot.get_chat_member = AsyncMock(
            return_value=MagicMock(status="creator")
        )
        assert await _is_admin(bot, -100100, 1) is True
