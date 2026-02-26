from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class QuizQuestion(Base):
    """A quiz question. Never deleted — only marked as used."""

    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(String(512), nullable=False)
    hint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    used_records: Mapped[list[QuizUsedQuestion]] = relationship(
        "QuizUsedQuestion", back_populates="question", cascade="all, delete-orphan"
    )


class QuizSession(Base):
    """Tracks an active quiz session in a chat topic."""

    __tablename__ = "quiz_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    topic_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    current_question_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("quiz_questions.id"), nullable=True
    )
    question_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    used_question_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    score_json: Mapped[str] = mapped_column(Text, default="{}")
    total_questions: Mapped[int] = mapped_column(Integer, default=10)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)

    def get_used_ids(self) -> list[int]:
        return json.loads(self.used_question_ids_json or "[]")

    def add_used_id(self, question_id: int) -> None:
        ids = self.get_used_ids()
        if question_id not in ids:
            ids.append(question_id)
        self.used_question_ids_json = json.dumps(ids)

    def get_scores(self) -> dict[int, int]:
        return {int(k): v for k, v in json.loads(self.score_json or "{}").items()}

    def add_score(self, user_id: int, points: int = 1) -> None:
        scores = self.get_scores()
        scores[user_id] = scores.get(user_id, 0) + points
        self.score_json = json.dumps(scores)


class QuizUsedQuestion(Base):
    """Records that a question was used in a session (avoids repeats)."""

    __tablename__ = "quiz_used_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quiz_questions.id"), nullable=False
    )
    used_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    question: Mapped[QuizQuestion] = relationship(
        "QuizQuestion", back_populates="used_records"
    )
