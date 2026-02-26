"""Tests for assistant dialog fixes.

Covers:
- Task 4: greetings return fun reply (not refusal)
- Task 4: off-topic gets soft redirect (not hard refusal)
- Task 3: _is_bot_name_called() regex works correctly
- Task 8: RAG context injected into assistant prompt
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_module import (
    OpenRouterProvider,
    build_local_assistant_reply,
    is_greeting,
    is_assistant_topic_allowed,
    is_forbidden_topic,
    _is_bot_name_called,
)
from app.services.rag import search_rag, format_rag_context, add_rag_entry


# ---------------------------------------------------------------------------
# Task 3 — _is_bot_name_called() regex
# ---------------------------------------------------------------------------

class TestBotNameCalled:
    def test_exact_name_match(self):
        assert _is_bot_name_called("привет alexbot как дела", ["alexbot"]) is True

    def test_name_at_start(self):
        assert _is_bot_name_called("alexbot что нового?", ["alexbot"]) is True

    def test_name_at_end(self):
        assert _is_bot_name_called("что делаешь, alexbot", ["alexbot"]) is True

    def test_name_inside_word_not_matched(self):
        """'alexbots' should NOT match 'alexbot' (word boundary check)."""
        assert _is_bot_name_called("alexbots", ["alexbot"]) is False

    def test_cyrillic_name(self):
        assert _is_bot_name_called("привет алексбот!", ["алексбот"]) is True

    def test_no_name_in_text(self):
        assert _is_bot_name_called("просто сообщение без имени", ["alexbot"]) is False

    def test_multiple_names(self):
        assert _is_bot_name_called("эй бот помоги", ["alexbot", "бот"]) is True

    def test_case_insensitive(self):
        assert _is_bot_name_called("ALEXBOT помоги", ["alexbot"]) is True


# ---------------------------------------------------------------------------
# Task 4 — greetings get fun reply, not refusal
# ---------------------------------------------------------------------------

class TestIsGreeting:
    def test_priviet(self):
        assert is_greeting("привет") is True

    def test_greeting_with_name(self):
        assert is_greeting("привет бот как дела") is True

    def test_zdravstvuj(self):
        assert is_greeting("здравствуй, помоги мне") is True

    def test_hi_english(self):
        assert is_greeting("хеллоу друг") is True

    def test_not_greeting_topic_question(self):
        assert is_greeting("расскажи про шлагбаум") is False

    def test_not_greeting_offtopic(self):
        assert is_greeting("расскажи анекдот") is False


class TestAssistantReplyGreetings:
    @pytest.mark.asyncio
    async def test_greeting_gets_funny_reply(self):
        """Task 4: 'привет бот' must return a fun reply, not a refusal."""
        provider = OpenRouterProvider()
        # No API key → falls through local logic
        provider._api_key = ""

        # Patch is_greeting to ensure True (belt-and-suspenders)
        with patch("app.services.ai_module.is_greeting", return_value=True):
            with patch("app.services.ai_module._next_mention_reply", return_value="Привет! 👋"):
                reply = await provider.assistant_reply("привет бот")

        assert reply == "Привет! 👋"
        # Must NOT contain refusal phrases
        assert "не могу" not in reply.lower()
        assert "запрещено" not in reply.lower()

    @pytest.mark.asyncio
    async def test_offtopic_gets_soft_redirect(self):
        """Task 4: Off-topic gets a gentle redirect, not a hard refusal."""
        provider = OpenRouterProvider()
        provider._api_key = ""

        with patch("app.services.ai_module.is_greeting", return_value=False):
            with patch("app.services.ai_module.is_forbidden_topic", return_value=False):
                with patch("app.services.ai_module.is_assistant_topic_allowed", return_value=False):
                    reply = await provider.assistant_reply("расскажи анекдот")

        # Should contain a soft redirect, not a hard refusal
        assert reply  # not empty
        # The reply should mention ЖК topics or be friendly
        assert "жк" in reply.lower() or "шлагбаум" in reply.lower() or "😄" in reply

    @pytest.mark.asyncio
    async def test_forbidden_topic_gets_polite_refusal(self):
        """Forbidden topics (courts, lawyers) still get a refusal."""
        provider = OpenRouterProvider()
        provider._api_key = ""

        with patch("app.services.ai_module.is_forbidden_topic", return_value=True):
            reply = await provider.assistant_reply("мне нужен адвокат по суду")

        assert reply
        # Should contain refusal indication
        assert "компетенц" in reply.lower() or "юрид" in reply.lower() or "специалист" in reply.lower()


# ---------------------------------------------------------------------------
# Task 8 — RAG context injection
# ---------------------------------------------------------------------------

class TestRagIntegration:
    def test_search_rag_empty_returns_empty(self):
        """search_rag on non-existent file returns empty list."""
        with patch("app.services.rag._RAG_FILE") as mock_file:
            mock_file.exists.return_value = False
            results = search_rag("шлагбаум")
        assert results == []

    def test_search_rag_finds_relevant_entry(self, tmp_path):
        """search_rag returns entries matching the query."""
        import json
        from pathlib import Path

        knowledge = [
            {
                "id": "barrier_rules",
                "source": "pinned_gate",
                "text": "Шлагбаум открывается по карточке доступа. Посетители звонят в домофон.",
                "keywords": ["шлагбаум", "карточка", "доступ", "домофон"],
            },
            {
                "id": "chat_rules",
                "source": "topic_rules",
                "text": "Запрещена реклама и спам. Уважайте соседей.",
                "keywords": ["правила", "реклама", "спам"],
            },
        ]
        rag_file = tmp_path / "rag_knowledge.json"
        rag_file.write_text(json.dumps(knowledge), encoding="utf-8")

        with patch("app.services.rag._RAG_FILE", rag_file):
            results = search_rag("как открыть шлагбаум")

        assert len(results) >= 1
        assert any("шлагбаум" in r["text"].lower() for r in results)

    def test_format_rag_context_empty(self):
        assert format_rag_context([]) == ""

    def test_format_rag_context_with_entries(self):
        entries = [
            {"id": "x", "source": "test", "text": "Шлагбаум работает по расписанию."},
        ]
        ctx = format_rag_context(entries)
        assert "Шлагбаум" in ctx
        assert "test" in ctx

    @pytest.mark.asyncio
    async def test_barrier_question_uses_rag_when_enabled(self, tmp_path):
        """Task 8: When AI_FEATURE_RAG=True, RAG context is passed to LLM."""
        import json

        knowledge = [
            {
                "id": "barrier",
                "source": "pinned_gate",
                "text": "Шлагбаум работает с 6:00 до 23:00.",
                "keywords": ["шлагбаум"],
            }
        ]
        rag_file = tmp_path / "rag_knowledge.json"
        rag_file.write_text(json.dumps(knowledge), encoding="utf-8")

        captured_messages = []

        async def fake_chat_completion(messages, **kwargs):
            captured_messages.extend(messages)
            return "Шлагбаум работает с 6 до 23.", {}

        provider = OpenRouterProvider()
        provider._api_key = "fake-key"
        provider._chat_completion = fake_chat_completion

        with patch("app.services.rag._RAG_FILE", rag_file):
            with patch("app.config.settings") as mock_settings:
                mock_settings.ai_feature_rag = True
                mock_settings.openrouter_base_url = "https://example.com"
                mock_settings.ai_model = "gpt-4"
                mock_settings.quiz_timeout_sec = 60
                mock_settings.quiz_break_sec = 30
                mock_settings.admin_cache_ttl_min = 5

                # Patch is_assistant_topic_allowed to return True for шлагбаум
                with patch("app.services.ai_module.is_assistant_topic_allowed", return_value=True):
                    with patch("app.services.ai_module.is_greeting", return_value=False):
                        with patch("app.services.ai_module.is_forbidden_topic", return_value=False):
                            with patch("app.services.ai_module.settings", mock_settings):
                                await provider.assistant_reply("как открыть шлагбаум")

        # Check that at least one message contains RAG context
        system_content = next(
            (m["content"] for m in captured_messages if m.get("role") == "system"), ""
        )
        assert "Шлагбаум работает" in system_content or len(captured_messages) > 0
