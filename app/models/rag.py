"""Модель для хранения RAG-сообщений из базы знаний чата ЖК."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RagMessage(Base):
    """Сообщение, добавленное администратором в базу знаний бота."""

    __tablename__ = "rag_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    added_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
