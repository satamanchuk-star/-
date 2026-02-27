from __future__ import annotations

import os
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    # Accepts BOT_TOKEN (preferred) or DOCKERHUB_TOKEN (legacy secret name)
    bot_token: str = Field(
        default="",
        validation_alias=AliasChoices("BOT_TOKEN", "DOCKERHUB_TOKEN"),
    )
    forum_chat_id: int = Field(default=0, alias="FORUM_CHAT_ID")
    topic_rules: int = Field(default=1, alias="TOPIC_RULES")
    topic_games: int = Field(default=2, alias="TOPIC_GAMES")
    topic_gate: int = Field(default=3, alias="TOPIC_GATE")
    topic_help: int = Field(default=4, alias="TOPIC_HELP")
    topic_general: int = Field(default=5, alias="TOPIC_GENERAL")

    # OpenRouter AI
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    ai_model: str = Field(default="openai/gpt-4o-mini", alias="AI_MODEL")
    ai_moderation_model: str = Field(
        default="openai/gpt-4o-mini", alias="AI_MODERATION_MODEL"
    )

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./alexbot.db", alias="DATABASE_URL"
    )

    # Quiz settings
    quiz_timeout_sec: int = Field(default=60, alias="QUIZ_TIMEOUT_SEC")
    quiz_break_sec: int = Field(default=30, alias="QUIZ_BREAK_SEC")
    quiz_max_sessions_per_day: int = Field(default=3, alias="QUIZ_MAX_SESSIONS_PER_DAY")

    # Admin cache
    admin_cache_ttl_min: int = Field(default=5, alias="ADMIN_CACHE_TTL_MIN")

    # RAG
    rag_auto_reload_hours: int = Field(default=24, alias="RAG_AUTO_RELOAD_HOURS")
    ai_feature_rag: bool = Field(default=False, alias="AI_FEATURE_RAG")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


settings = Settings()
