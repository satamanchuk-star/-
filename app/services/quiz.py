"""Quiz service — manages sessions, questions, scoring, and timing.

Fixes applied in this file:
- Task 1  [CRITICAL]: end_quiz_session() no longer deletes quiz_questions rows.
          quiz_used_questions already tracks what was asked.
- Task 7:  build_answer_hint() now shows the actual word count.
- Task 10: QUIZ_BREAK_BETWEEN_QUESTIONS_SEC default reduced to 30 s (was 60).
           Both constants are now read from env via settings.
- Task 4.1: Race-condition guard (_quiz_finishing set) prevents double-finish.
- Task 4.3: local_quiz_answer_decision() uses strict single-word matching.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.quiz import QuizQuestion, QuizSession, QuizUsedQuestion

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable timeouts (Task 10)
# ---------------------------------------------------------------------------
QUIZ_QUESTION_TIMEOUT_SEC: int = settings.quiz_timeout_sec          # default 60
QUIZ_BREAK_BETWEEN_QUESTIONS_SEC: int = settings.quiz_break_sec     # default 30 (was 60)

QUIZ_TOTAL_QUESTIONS = 10

# ---------------------------------------------------------------------------
# Race-condition guard (Task 4.1)
# ---------------------------------------------------------------------------
# Set of (chat_id, topic_id) pairs that are currently being finalized.
_quiz_finishing: set[tuple[int, int]] = set()

# Pending asyncio task handles for timeout / break timers
_timeout_tasks: dict[tuple[int, int], asyncio.Task] = {}
_grace_tasks: dict[tuple[int, int], asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Lowercase, strip diacritics, remove punctuation."""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_words(text: str) -> list[str]:
    """Return a list of normalized words from *text*."""
    return [w for w in _normalize_text(text).split() if w]


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (ca != cb), curr[j] + 1, prev[j + 1] + 1))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# Answer hint (Task 7)
# ---------------------------------------------------------------------------

def build_answer_hint(answer: str) -> str:
    """Return a useful hint about the answer format.

    Fix (Task 7): previously returned generic 'В ответе много слов' for
    multi-word answers. Now shows the actual word count and letter count for
    single-word answers.
    """
    words = _normalize_words(answer)
    count = len(words)
    if count == 0:
        return "Подсказка недоступна."
    if count == 1:
        return f"Ответ: 1 слово ({len(answer.strip())} букв)."
    if count == 2:
        return "Ответ: 2 слова."
    return f"Ответ: {count} слова(-ов)."


# ---------------------------------------------------------------------------
# Answer decision (Task 4.3)
# ---------------------------------------------------------------------------

class _Decision:
    __slots__ = ("is_correct", "is_close", "ratio")

    def __init__(self, is_correct: bool, is_close: bool, ratio: float) -> None:
        self.is_correct = is_correct
        self.is_close = is_close
        self.ratio = ratio

    def __bool__(self) -> bool:
        return self.is_correct


def _correct_decision() -> _Decision:
    return _Decision(is_correct=True, is_close=False, ratio=1.0)


def _close_decision() -> _Decision:
    return _Decision(is_correct=True, is_close=True, ratio=0.9)


def _wrong_decision() -> _Decision:
    return _Decision(is_correct=False, is_close=False, ratio=0.0)


def local_quiz_answer_decision(correct_answer: str, user_answer: str) -> _Decision:
    """Decide whether *user_answer* matches *correct_answer*.

    Fix (Task 4.3): For single-word answers the old implementation used set
    overlap which meant 'не Нил' would match 'Нил' (ratio 1.0).
    Now:
    - Single-word answers require the user to provide exactly one word
      that either exactly matches or has Levenshtein distance ≤ 1.
    - Multi-word answers still use overlap ratio ≥ 0.8.
    """
    correct_words = _normalize_words(correct_answer)
    answer_words = _normalize_words(user_answer)

    if not correct_words:
        return _wrong_decision()

    if len(correct_words) == 1:
        # Strict single-word mode (Task 4.3)
        correct_word = correct_words[0]
        if len(answer_words) != 1:
            # Multi-word answer for a single-word question → wrong
            return _wrong_decision()
        answer_word = answer_words[0]
        if correct_word == answer_word:
            return _correct_decision()
        if _levenshtein(correct_word, answer_word) <= 1:
            return _close_decision()
        return _wrong_decision()

    # Multi-word: overlap ratio
    correct_set = set(correct_words)
    answer_set = set(answer_words)
    if not answer_set:
        return _wrong_decision()
    overlap = len(correct_set & answer_set)
    ratio = overlap / len(correct_set)
    if ratio >= 1.0:
        return _correct_decision()
    if ratio >= 0.8:
        return _close_decision()
    return _wrong_decision()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def get_active_session(
    session: AsyncSession, chat_id: int, topic_id: int
) -> Optional[QuizSession]:
    result = await session.execute(
        select(QuizSession).where(
            QuizSession.chat_id == chat_id,
            QuizSession.topic_id == topic_id,
            QuizSession.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_next_question(
    session: AsyncSession, chat_id: int, used_ids: list[int]
) -> Optional[QuizQuestion]:
    """Return a random question not yet used in this chat."""
    stmt = select(QuizQuestion)
    if used_ids:
        stmt = stmt.where(QuizQuestion.id.not_in(used_ids))
    # Also exclude globally used questions for this chat
    globally_used = (
        select(QuizUsedQuestion.question_id)
        .where(QuizUsedQuestion.chat_id == chat_id)
    )
    stmt = stmt.where(QuizQuestion.id.not_in(globally_used))
    result = await session.execute(stmt)
    questions = result.scalars().all()
    if not questions:
        # All questions used globally — reset the used list
        return None
    import random
    return random.choice(questions)


async def mark_question_used(
    session: AsyncSession, chat_id: int, question_id: int
) -> None:
    """Record *question_id* as used in *chat_id*."""
    record = QuizUsedQuestion(chat_id=chat_id, question_id=question_id)
    session.add(record)
    await session.flush()


async def reset_used_questions(session: AsyncSession, chat_id: int) -> int:
    """Delete all QuizUsedQuestion records for *chat_id*.

    Used by /reset_used_questions admin command when all questions are exhausted.
    """
    result = await session.execute(
        delete(QuizUsedQuestion).where(QuizUsedQuestion.chat_id == chat_id)
    )
    await session.flush()
    return result.rowcount


# ---------------------------------------------------------------------------
# Session lifecycle (Task 1 CRITICAL FIX)
# ---------------------------------------------------------------------------

async def start_quiz_session(
    session: AsyncSession, chat_id: int, topic_id: int
) -> QuizSession:
    """Create and persist a new quiz session."""
    quiz_session = QuizSession(
        chat_id=chat_id,
        topic_id=topic_id,
        is_active=True,
        total_questions=QUIZ_TOTAL_QUESTIONS,
    )
    session.add(quiz_session)
    await session.flush()
    return quiz_session


async def end_quiz_session(
    session: AsyncSession, quiz_session: QuizSession
) -> None:
    """Mark a quiz session as finished.

    Fix (Task 1) [CRITICAL]: The original code executed
        DELETE FROM quiz_questions WHERE id IN (used_ids)
    which permanently destroyed questions after every session!

    The correct approach: only mark the session inactive and clear the current
    question pointer. The quiz_used_questions table already records which
    questions were asked, and quiz_questions rows must NEVER be deleted here.
    """
    quiz_session.is_active = False
    quiz_session.current_question_id = None
    quiz_session.ended_at = datetime.now(timezone.utc)
    # DO NOT delete from quiz_questions — they are needed for future sessions.
    # quiz_used_questions already tracks what was asked.
    await session.flush()


# ---------------------------------------------------------------------------
# Race-condition guard (Task 4.1)
# ---------------------------------------------------------------------------

async def safe_finish_quiz(
    session: AsyncSession,
    bot: "Bot",
    chat_id: int,
    topic_id: int,
    quiz_session: QuizSession,
    notify_callback,  # async callable(bot, chat_id, topic_id, quiz_session)
) -> None:
    """Finalize a quiz session with a guard against concurrent finalization.

    Fix (Task 4.1): Both _handle_timeout() and _finalize_answers_after_grace()
    could try to finish the same session simultaneously. This function ensures
    only one coroutine proceeds.
    """
    key = (chat_id, topic_id)
    if key in _quiz_finishing:
        return  # Another coroutine is already finishing this session
    _quiz_finishing.add(key)
    try:
        await end_quiz_session(session, quiz_session)
        await session.commit()
        await notify_callback(bot, chat_id, topic_id, quiz_session)
    except Exception:
        logger.exception("Error finishing quiz session (%d, %d)", chat_id, topic_id)
        await session.rollback()
    finally:
        _quiz_finishing.discard(key)


# ---------------------------------------------------------------------------
# Timer management
# ---------------------------------------------------------------------------

def cancel_timeout(chat_id: int, topic_id: int) -> None:
    key = (chat_id, topic_id)
    task = _timeout_tasks.pop(key, None)
    if task and not task.done():
        task.cancel()


def cancel_grace(chat_id: int, topic_id: int) -> None:
    key = (chat_id, topic_id)
    task = _grace_tasks.pop(key, None)
    if task and not task.done():
        task.cancel()


def schedule_timeout(
    chat_id: int, topic_id: int, coro
) -> asyncio.Task:
    cancel_timeout(chat_id, topic_id)
    task = asyncio.create_task(coro)
    _timeout_tasks[(chat_id, topic_id)] = task
    return task


def schedule_grace(
    chat_id: int, topic_id: int, coro
) -> asyncio.Task:
    cancel_grace(chat_id, topic_id)
    task = asyncio.create_task(coro)
    _grace_tasks[(chat_id, topic_id)] = task
    return task


def cancel_all_timers(chat_id: int, topic_id: int) -> None:
    cancel_timeout(chat_id, topic_id)
    cancel_grace(chat_id, topic_id)
