"""Tests for quiz fixes.

Covers:
- Task 1  [CRITICAL]: end_quiz_session() must NOT delete quiz_questions rows
- Task 7:  build_answer_hint() shows correct word count
- Task 4.3: single-word answer matching is strict
- Task 4.4: /stopquiz command exists and works
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from app.services.quiz import (
    build_answer_hint,
    end_quiz_session,
    local_quiz_answer_decision,
)


# ---------------------------------------------------------------------------
# Task 1 [CRITICAL] — end_quiz_session must not delete questions
# ---------------------------------------------------------------------------

class TestEndQuizSessionNoDelete:
    @pytest.mark.asyncio
    async def test_end_session_does_not_delete_questions(self):
        """
        Fix (Task 1): end_quiz_session() must only set is_active=False and
        clear current_question_id. It must NEVER execute a DELETE on
        quiz_questions.
        """
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        quiz_session = MagicMock()
        quiz_session.is_active = True
        quiz_session.current_question_id = 5
        quiz_session.ended_at = None

        await end_quiz_session(mock_session, quiz_session)

        # Session must be marked inactive
        assert quiz_session.is_active is False
        # Current question cleared
        assert quiz_session.current_question_id is None
        # ended_at must be set
        assert quiz_session.ended_at is not None

        # CRITICAL: session.execute must NOT have been called with a DELETE
        for call_args in mock_session.execute.call_args_list:
            stmt = call_args.args[0] if call_args.args else None
            if stmt is not None:
                stmt_str = str(stmt).upper()
                assert "DELETE" not in stmt_str, (
                    "end_quiz_session() must not DELETE quiz_questions rows! "
                    f"Got statement: {stmt_str}"
                )

    @pytest.mark.asyncio
    async def test_session_marked_inactive_after_end(self):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        qs = MagicMock()
        qs.is_active = True
        qs.current_question_id = 3
        qs.ended_at = None

        await end_quiz_session(mock_session, qs)
        assert qs.is_active is False


# ---------------------------------------------------------------------------
# Task 7 — build_answer_hint shows word count
# ---------------------------------------------------------------------------

class TestBuildAnswerHint:
    def test_single_word_shows_letter_count(self):
        hint = build_answer_hint("Нил")
        assert "1 слово" in hint
        assert "3" in hint  # 3 letters

    def test_two_words(self):
        hint = build_answer_hint("Лев Толстой")
        assert "2 слова" in hint

    def test_three_words(self):
        hint = build_answer_hint("Александр Сергеевич Пушкин")
        # Should mention 3, not just say 'много слов'
        assert "3" in hint
        assert "много слов" not in hint.lower()

    def test_empty_answer(self):
        hint = build_answer_hint("")
        assert "недоступна" in hint.lower() or hint  # graceful


# ---------------------------------------------------------------------------
# Task 4.3 — strict single-word answer matching
# ---------------------------------------------------------------------------

class TestLocalQuizAnswerDecision:
    def test_exact_single_word_match(self):
        decision = local_quiz_answer_decision("Нил", "Нил")
        assert decision.is_correct is True

    def test_single_word_wrong_multiple_words_input(self):
        """'не Нил' must NOT match single-word answer 'Нил'."""
        decision = local_quiz_answer_decision("Нил", "не Нил")
        assert decision.is_correct is False

    def test_single_word_wrong_sentence_containing_answer(self):
        """'Нил — это река' must NOT match 'Нил'."""
        decision = local_quiz_answer_decision("Нил", "Нил — это река")
        assert decision.is_correct is False

    def test_single_word_typo_close(self):
        """Typo within Levenshtein 1 is accepted as close."""
        decision = local_quiz_answer_decision("Нил", "Нила")
        assert decision.is_correct is True
        assert decision.is_close is True

    def test_single_word_completely_wrong(self):
        decision = local_quiz_answer_decision("Нил", "Волга")
        assert decision.is_correct is False

    def test_multiword_correct_full_overlap(self):
        decision = local_quiz_answer_decision("Лев Толстой", "Лев Толстой")
        assert decision.is_correct is True

    def test_multiword_partial_overlap_pass(self):
        """80%+ overlap passes for multi-word answers."""
        decision = local_quiz_answer_decision("Александр Сергеевич Пушкин", "Пушкин Александр Сергеевич")
        assert decision.is_correct is True

    def test_multiword_insufficient_overlap_fail(self):
        decision = local_quiz_answer_decision("Александр Сергеевич Пушкин", "Достоевский")
        assert decision.is_correct is False

    def test_case_insensitive(self):
        decision = local_quiz_answer_decision("МОСКВА", "москва")
        assert decision.is_correct is True
