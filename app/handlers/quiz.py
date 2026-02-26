"""Quiz handler — Telegram command handlers for the quiz feature.

Includes:
- /startquiz  start a new quiz session
- /stopquiz   admin command to forcibly end the current session (Task 4.4)
- /reset_used_questions  admin command to reset the used-questions list (Task 1)
- Answer handling
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.models.base import get_session
from app.services.quiz import (
    QUIZ_BREAK_BETWEEN_QUESTIONS_SEC,
    QUIZ_QUESTION_TIMEOUT_SEC,
    QUIZ_TOTAL_QUESTIONS,
    build_answer_hint,
    cancel_all_timers,
    end_quiz_session,
    get_active_session,
    get_next_question,
    local_quiz_answer_decision,
    mark_question_used,
    reset_used_questions,
    safe_finish_quiz,
    schedule_grace,
    schedule_timeout,
    start_quiz_session,
)
from app.utils.admin import is_admin

router = Router(name="quiz")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _send_question(
    bot: Bot,
    chat_id: int,
    topic_id: int,
    quiz_session,
) -> None:
    """Fetch next question, send it, and start timeout timer."""
    async for session in get_session():
        used_ids = quiz_session.get_used_ids()
        question = await get_next_question(session, chat_id, used_ids)
        if question is None:
            # No more questions
            await safe_finish_quiz(
                session, bot, chat_id, topic_id, quiz_session, _notify_results
            )
            return

        quiz_session.current_question_id = question.id
        quiz_session.question_started_at = datetime.now(timezone.utc)
        quiz_session.add_used_id(question.id)
        quiz_session.questions_asked += 1
        await mark_question_used(session, chat_id, question.id)
        await session.commit()

        hint = build_answer_hint(question.answer)
        await bot.send_message(
            chat_id,
            f"❓ <b>Вопрос {quiz_session.questions_asked}/{QUIZ_TOTAL_QUESTIONS}:</b>\n"
            f"{question.question}\n\n"
            f"💡 {hint}",
            parse_mode="HTML",
            message_thread_id=topic_id,
        )

        question_started_at = quiz_session.question_started_at

        async def _timeout_handler() -> None:
            await asyncio.sleep(QUIZ_QUESTION_TIMEOUT_SEC)
            async for s in get_session():
                qs = await get_active_session(s, chat_id, topic_id)
                if not qs:
                    return
                # Check this is still the same question
                if qs.question_started_at != question_started_at:
                    return
                await bot.send_message(
                    chat_id,
                    f"⏰ Время вышло! Правильный ответ: <b>{question.answer}</b>",
                    parse_mode="HTML",
                    message_thread_id=topic_id,
                )
                if qs.questions_asked >= QUIZ_TOTAL_QUESTIONS:
                    await safe_finish_quiz(s, bot, chat_id, topic_id, qs, _notify_results)
                else:
                    await asyncio.sleep(QUIZ_BREAK_BETWEEN_QUESTIONS_SEC)
                    await _send_question(bot, chat_id, topic_id, qs)

        schedule_timeout(chat_id, topic_id, _timeout_handler())
        break


async def _notify_results(
    bot: Bot,
    chat_id: int,
    topic_id: int,
    quiz_session,
) -> None:
    """Send final scoreboard message."""
    scores = quiz_session.get_scores()
    if not scores:
        text = "🏁 Викторина завершена! Никто не ответил правильно 😢"
    else:
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        lines = ["🏆 <b>Результаты викторины:</b>"]
        for rank, (user_id, pts) in enumerate(sorted_scores, 1):
            lines.append(f"{rank}. user_{user_id}: {pts} очк.")
        text = "\n".join(lines)
    await bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        message_thread_id=topic_id,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@router.message(Command("startquiz"))
async def cmd_start_quiz(message: Message, bot: Bot) -> None:
    if message.chat.id != settings.forum_chat_id:
        return
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        await message.reply("Только администраторы могут запускать викторину.")
        return

    topic_id = message.message_thread_id or settings.topic_games

    async for session in get_session():
        existing = await get_active_session(session, settings.forum_chat_id, topic_id)
        if existing:
            await message.reply("Викторина уже идёт!")
            return
        quiz_session = await start_quiz_session(session, settings.forum_chat_id, topic_id)
        await session.commit()

    await message.reply("🎮 Викторина начинается! Приготовьтесь...")
    await _send_question(bot, settings.forum_chat_id, topic_id, quiz_session)


@router.message(Command("stopquiz"))
async def cmd_stop_quiz(message: Message, bot: Bot) -> None:
    """Admin command to forcibly stop the current quiz session. (Task 4.4)"""
    if message.chat.id != settings.forum_chat_id:
        return
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        await message.reply("Только администраторы могут останавливать викторину.")
        return

    topic_id = message.message_thread_id or settings.topic_games
    cancel_all_timers(settings.forum_chat_id, topic_id)

    async for session in get_session():
        quiz_session = await get_active_session(session, settings.forum_chat_id, topic_id)
        if not quiz_session:
            await message.reply("Нет активной викторины.")
            return
        await safe_finish_quiz(
            session, bot, settings.forum_chat_id, topic_id, quiz_session, _notify_results
        )
        break

    await message.reply("⏹ Викторина остановлена администратором.")


@router.message(Command("reset_used_questions"))
async def cmd_reset_used(message: Message, bot: Bot) -> None:
    """Admin command to reset the used-questions list. (Task 1 supplement)"""
    if not await is_admin(bot, settings.forum_chat_id, message.from_user.id):
        return
    async for session in get_session():
        count = await reset_used_questions(session, settings.forum_chat_id)
        await session.commit()
        await message.reply(f"✅ Сброшено {count} использованных вопросов.")
        break


@router.message(F.text)
async def handle_quiz_answer(message: Message, bot: Bot) -> None:
    """Process a possible quiz answer from any user in the games topic."""
    if message.chat.id != settings.forum_chat_id:
        raise SkipHandler
    if not message.text or not message.from_user:
        raise SkipHandler

    topic_id = message.message_thread_id or settings.topic_games
    if topic_id != settings.topic_games:
        raise SkipHandler  # Only in games topic

    async for session in get_session():
        quiz_session = await get_active_session(session, settings.forum_chat_id, topic_id)
        if not quiz_session or not quiz_session.current_question_id:
            raise SkipHandler

        # Fetch current question
        from sqlalchemy import select
        from app.models.quiz import QuizQuestion
        result = await session.execute(
            select(QuizQuestion).where(QuizQuestion.id == quiz_session.current_question_id)
        )
        question = result.scalar_one_or_none()
        if not question:
            return

        decision = local_quiz_answer_decision(question.answer, message.text)
        if decision.is_correct:
            cancel_all_timers(settings.forum_chat_id, topic_id)
            quiz_session.add_score(message.from_user.id)
            quiz_session.current_question_id = None

            suffix = " (почти точно!)" if decision.is_close else ""
            await message.reply(
                f"✅ Верно{suffix}! Правильный ответ: <b>{question.answer}</b>",
                parse_mode="HTML",
            )

            if quiz_session.questions_asked >= QUIZ_TOTAL_QUESTIONS:
                await safe_finish_quiz(
                    session, bot, settings.forum_chat_id, topic_id, quiz_session, _notify_results
                )
            else:
                await session.commit()
                await asyncio.sleep(QUIZ_BREAK_BETWEEN_QUESTIONS_SEC)
                await _send_question(bot, settings.forum_chat_id, topic_id, quiz_session)
        break
