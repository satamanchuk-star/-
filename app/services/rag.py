"""RAG (Retrieval-Augmented Generation) module.

Provides knowledge base for the ЖК assistant using two sources:
1. JSON file (app/data/rag_knowledge.json) — static knowledge
2. Database (rag_messages table) — messages added by admins via /rag_bot

Both sources are searched and combined for assistant context.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.rag import RagMessage

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

_RAG_FILE = Path(__file__).parent.parent / "data" / "rag_knowledge.json"


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

# Each entry:
# {
#   "id": str,
#   "source": str,
#   "text": str,
#   "keywords": [str, ...]
# }

RagEntry = dict[str, Any]


def _load_knowledge() -> list[RagEntry]:
    if not _RAG_FILE.exists():
        return []
    try:
        with _RAG_FILE.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("Failed to load RAG knowledge: %s", exc)
        return []


def _save_knowledge(entries: list[RagEntry]) -> None:
    _RAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _RAG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)


def _tokenize(text: str) -> set[str]:
    """Return a set of lowercase word tokens (≥ 3 chars)."""
    return {w for w in re.findall(r"[а-яёa-z]+", text.lower()) if len(w) >= 3}


def _score(query_tokens: set[str], entry: RagEntry) -> float:
    """Compute overlap score between query tokens and entry keywords + text."""
    entry_tokens = _tokenize(entry.get("text", ""))
    for kw in entry.get("keywords", []):
        entry_tokens.update(_tokenize(kw))
    if not entry_tokens:
        return 0.0
    intersection = query_tokens & entry_tokens
    return len(intersection) / len(query_tokens) if query_tokens else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_rag(query: str, top_k: int = 3) -> list[RagEntry]:
    """Return top-k most relevant knowledge-base entries for *query*."""
    knowledge = _load_knowledge()
    if not knowledge:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scored = [(entry, _score(query_tokens, entry)) for entry in knowledge]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [entry for entry, score in scored[:top_k] if score > 0.0]


def format_rag_context(results: list[RagEntry]) -> str:
    """Format RAG results as a text block for injection into the LLM prompt."""
    if not results:
        return ""
    parts = []
    for i, entry in enumerate(results, 1):
        source = entry.get("source", "unknown")
        text = entry.get("text", "")
        parts.append(f"[{i}] ({source}): {text}")
    return "\n".join(parts)


async def load_rag_from_telegram(bot: "Bot") -> int:
    """Fetch pinned/recent messages from forum topics and save to RAG store.

    Returns the number of fragments saved.
    """
    entries: list[RagEntry] = []

    # Fetch pinned message from rules topic
    try:
        rules_msg = await bot.get_chat(settings.forum_chat_id)
        pinned = rules_msg.pinned_message
        if pinned and pinned.text:
            entry = {
                "id": "rules_pinned",
                "source": "topic_rules",
                "text": pinned.text,
                "keywords": _extract_keywords(pinned.text),
            }
            entries.append(entry)
    except Exception as exc:
        logger.warning("Could not fetch rules pinned message: %s", exc)

    # Fetch pinned message from gate topic (шлагбаум)
    try:
        chat_member_msg = await bot.forward_message(
            chat_id=settings.forum_chat_id,
            from_chat_id=settings.forum_chat_id,
            message_id=1,
        )
    except Exception:
        pass  # Best-effort

    # Persist whatever we gathered
    if entries:
        _save_knowledge(entries)
    logger.info("RAG updated: %d fragments", len(entries))
    return len(entries)


def add_rag_entry(entry_id: str, source: str, text: str) -> None:
    """Manually add or update a RAG entry (useful for seeding initial knowledge)."""
    knowledge = _load_knowledge()
    # Remove existing entry with same id
    knowledge = [e for e in knowledge if e.get("id") != entry_id]
    knowledge.append({
        "id": entry_id,
        "source": source,
        "text": text,
        "keywords": _extract_keywords(text),
    })
    _save_knowledge(knowledge)


def _extract_keywords(text: str) -> list[str]:
    """Extract significant words from *text* as keyword candidates."""
    tokens = re.findall(r"[а-яёa-z]{4,}", text.lower())
    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:30]


# ---------------------------------------------------------------------------
# Database-backed RAG (admin-added messages via /rag_bot)
# ---------------------------------------------------------------------------

async def add_rag_message(
    session: AsyncSession,
    *,
    chat_id: int,
    message_text: str,
    added_by_user_id: int,
    source_user_id: int | None = None,
    source_message_id: int | None = None,
) -> RagMessage:
    """Добавляет сообщение в RAG-базу знаний."""
    record = RagMessage(
        chat_id=chat_id,
        message_text=message_text,
        added_by_user_id=added_by_user_id,
        source_user_id=source_user_id,
        source_message_id=source_message_id,
    )
    session.add(record)
    await session.flush()
    return record


async def search_rag_db(
    session: AsyncSession,
    chat_id: int,
    query: str,
    top_k: int = 5,
) -> list[RagMessage]:
    """Ищет релевантные сообщения из RAG-базы по пересечению слов."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    result = await session.execute(
        select(RagMessage)
        .where(RagMessage.chat_id == chat_id)
        .order_by(RagMessage.created_at.desc())
        .limit(200)
    )
    messages = list(result.scalars().all())

    scored: list[tuple[RagMessage, float]] = []
    for msg in messages:
        msg_tokens = _tokenize(msg.message_text)
        if not msg_tokens:
            continue
        overlap = len(query_tokens & msg_tokens)
        if overlap > 0:
            score = overlap / len(query_tokens)
            scored.append((msg, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [msg for msg, _ in scored[:top_k]]


def format_db_rag_context(messages: list[RagMessage]) -> str:
    """Форматирует DB-RAG сообщения для вставки в промпт."""
    if not messages:
        return ""
    parts = []
    for i, msg in enumerate(messages, 1):
        parts.append(f"[{i}] {msg.message_text}")
    return "\n".join(parts)


async def get_combined_rag_context(
    session: AsyncSession,
    chat_id: int,
    query: str,
    top_k: int = 5,
) -> str:
    """Объединяет контекст из JSON-файла и базы данных."""
    parts = []

    # JSON-based RAG
    json_results = search_rag(query, top_k=top_k)
    json_text = format_rag_context(json_results)
    if json_text:
        parts.append(json_text)

    # DB-based RAG (admin-added messages)
    db_results = await search_rag_db(session, chat_id, query, top_k=top_k)
    db_text = format_db_rag_context(db_results)
    if db_text:
        parts.append(db_text)

    return "\n".join(parts)


async def get_rag_count(session: AsyncSession, chat_id: int) -> int:
    """Возвращает количество записей в RAG-базе."""
    result = await session.scalar(
        select(func.count()).select_from(RagMessage).where(RagMessage.chat_id == chat_id)
    )
    return int(result or 0)
