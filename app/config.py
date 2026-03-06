from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Load environment variables from the server's docker-compose.yaml
# ---------------------------------------------------------------------------
_COMPOSE_FILE = Path("/opt/alexbot/docker-compose.yaml")


def _parse_env_from_compose(path: Path) -> dict[str, str]:
    """Extract environment variables from docker-compose.yaml."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    env_vars: dict[str, str] = {}
    in_environment = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "environment:":
            in_environment = True
            continue
        if in_environment:
            if not stripped or stripped.startswith("#"):
                continue
            # "- KEY=VALUE" format
            m = re.match(r"^-\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", stripped)
            if m:
                env_vars[m.group(1)] = m.group(2).strip().strip("'\"")
                continue
            # "KEY: VALUE" format
            m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*:\s*(.+)$", stripped)
            if m:
                env_vars[m.group(1)] = m.group(2).strip().strip("'\"")
                continue
            # Any other non-indented/non-env line ends the section
            if not stripped.startswith("-") and "=" not in stripped:
                in_environment = False
    return env_vars


_compose_env = _parse_env_from_compose(_COMPOSE_FILE)
for _k, _v in _compose_env.items():
    if _k not in os.environ:
        os.environ[_k] = _v


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
