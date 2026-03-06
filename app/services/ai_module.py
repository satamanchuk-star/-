"""AI moderation and assistant logic backed by OpenRouter.

Fixes applied in this file:
- Task 2:  detect_profanity() now uses profanity.txt via utils/profanity.py
- Task 2:  normalize_for_profanity() extended with full transliteration table
- Task 4:  assistant_reply() handles greetings and off-topic before topic check
- Task 3:  _is_bot_name_called() regex fixed (was double-escaped \\w)
- Task 9:  datetime.now(timezone.utc) replaces deprecated datetime.utcnow()
"""
from __future__ import annotations

import itertools
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp

from app.config import settings
from app.utils.profanity import load_profanity, load_profanity_exceptions
from app.utils.text import contains_profanity, split_profanity_words

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level profanity dictionaries (loaded once at import time)
# ---------------------------------------------------------------------------
_PROFANITY_ROOTS: list[str] = load_profanity()
_PROFANITY_EXCEPTIONS: list[str] = load_profanity_exceptions()

# ---------------------------------------------------------------------------
# Transliteration table for normalize_for_profanity()
# ---------------------------------------------------------------------------
_TRANSLIT_TABLE: list[tuple[str, str]] = [
    # Full-word mappings first (longest possible matches)
    ("blyad", "бляд"),
    ("bljad", "бляд"),
    ("bliad", "бляд"),
    # Multi-char sequences (longer matches before single chars)
    ("bly", "бля"),
    ("blja", "бля"),
    ("blia", "бля"),
    ("pizd", "пизд"),
    ("pisd", "пизд"),
    ("pisд", "пизд"),
    ("xuy", "хуй"),
    ("xuj", "хуй"),
    ("khuy", "хуй"),
    ("khuj", "хуй"),
    ("huy", "хуй"),
    ("huj", "хуй"),
    ("suk", "сук"),
    ("cyk", "сук"),
    ("mud", "муд"),
    ("myd", "муд"),
    ("eby", "ебы"),
    ("eban", "ебан"),
    ("yoban", "ёбан"),
    ("yob", "ёб"),
    ("jeb", "еб"),
    # Latin → Cyrillic single chars (applied after multi-char)
    ("ph", "ф"),
    ("a", "а"),
    ("b", "б"),
    ("c", "с"),
    ("d", "д"),
    ("e", "е"),
    ("f", "ф"),
    ("g", "г"),
    ("h", "х"),
    ("i", "и"),
    ("j", "й"),
    ("k", "к"),
    ("l", "л"),
    ("m", "м"),
    ("n", "н"),
    ("o", "о"),
    ("p", "п"),
    ("q", "к"),
    ("r", "р"),
    ("s", "с"),
    ("t", "т"),
    ("u", "у"),
    ("v", "в"),
    ("w", "в"),
    ("x", "х"),
    ("y", "у"),
    ("z", "з"),
    # Digits / special chars used as letter substitutes
    ("0", "о"),
    ("1", "и"),
    ("3", "з"),
    ("4", "ч"),
    ("5", "б"),
    ("6", "б"),
    ("!", "и"),
    ("@", "а"),
    ("$", "с"),
    # ё→е normalisation in dictionary lookups
    ("ё", "е"),
]


def normalize_for_profanity(text: str) -> str:
    """Normalize *text* for profanity detection.

    Applies:
    1. Lowercase conversion
    2. Multi-char transliteration (Latin sequences → Cyrillic)
    3. Single-char Latin → Cyrillic mapping
    4. Digit/special-char → letter mapping
    5. Removal of non-alphabetic characters (after conversion)

    Fix (Task 2): previously only 6 basic Latin→Cyrillic substitutions were
    made. Now a full transliteration table handles common leet/translit tricks.
    """
    result = text.lower()
    # Apply multi-char rules first (they are listed first in _TRANSLIT_TABLE)
    for src, dst in _TRANSLIT_TABLE:
        result = result.replace(src, dst)
    # Remove remaining non-Cyrillic/non-letter characters
    result = re.sub(r"[^а-яё]", "", result)
    return result


# ---------------------------------------------------------------------------
# Profanity detection
# ---------------------------------------------------------------------------

# Fallback hard-coded roots (kept for safety in case profanity.txt is missing)
_FALLBACK_ROOTS = ["хуй", "хуе", "пизд", "ебл", "сука", "блядь", "мудак"]


def detect_profanity(text: str) -> bool:
    """Return True if *text* contains profanity.

    Fix (Task 2): now uses profanity.txt (loaded into _PROFANITY_ROOTS) in
    addition to the fallback hard-coded list, and applies full transliteration.
    """
    roots = _PROFANITY_ROOTS if _PROFANITY_ROOTS else _FALLBACK_ROOTS
    exceptions = _PROFANITY_EXCEPTIONS

    # Check both original and normalized forms
    for variant in (text, normalize_for_profanity(text)):
        words = split_profanity_words(variant)
        if contains_profanity(words, roots, exceptions):
            return True
    return False


# ---------------------------------------------------------------------------
# Reload hook (called by /reload_profanity command)
# ---------------------------------------------------------------------------

def reload_profanity_dicts() -> int:
    """Reload profanity.txt and exceptions from disk; return count of roots."""
    global _PROFANITY_ROOTS, _PROFANITY_EXCEPTIONS
    _PROFANITY_ROOTS = load_profanity()
    _PROFANITY_EXCEPTIONS = load_profanity_exceptions()
    logger.info("Profanity dicts reloaded: %d roots, %d exceptions",
                len(_PROFANITY_ROOTS), len(_PROFANITY_EXCEPTIONS))
    return len(_PROFANITY_ROOTS)


# ---------------------------------------------------------------------------
# Allowed / forbidden topic lists for assistant
# ---------------------------------------------------------------------------

_ALLOWED_ASSISTANT_TOPICS = (
    "жк",
    "жилой",
    "комплекс",
    "шлагбаум",
    "въезд",
    "выезд",
    "парковк",
    "сосед",
    "управляющ",
    "ук ",
    "тсж",
    "правил",
    "форум",
    "топик",
    "подъезд",
    "лифт",
    "мусор",
    "уборк",
    "консьерж",
    "охран",
    "домофон",
    "квартир",
    "чат",
    "сообществ",
    "администратор",
    "баннер",
    "объявлен",
    "собственник",
    "арендатор",
    # Expanded topics for better context understanding
    "ворота",
    "пропуск",
    "карточк",
    "ключ",
    "дверь",
    "замок",
    "стоянк",
    "машин",
    "авто",
    "площадк",
    "детск",
    "ребёнок",
    "ребенок",
    "качел",
    "горк",
    "собак",
    "кошк",
    "животн",
    "питом",
    "выгул",
    "шум",
    "тишин",
    "громк",
    "ремонт",
    "перепланировк",
    "стройк",
    "курьер",
    "доставк",
    "посылк",
    "постамат",
    "почт",
    "камер",
    "видеонаблюден",
    "безопасност",
    "диспетчер",
    "заявк",
    "жалоб",
    "авари",
    "протечк",
    "отоплен",
    "водоснабжен",
    "электричеств",
    "свет",
    "газ",
    "счётчик",
    "счетчик",
    "оплат",
    "квитанц",
    "жкх",
    "двор",
    "территори",
    "озеленен",
    "клумб",
    "газон",
    "контейнер",
    "помойк",
)

_FORBIDDEN_ASSISTANT_TOPICS = (
    "суд",
    "адвокат",
    "юрист",
    "прокурор",
    "полиция",
    "уголовн",
    "следствен",
    "приставы",
    "банкрот",
    "налог",
    "завещани",
    "наследств",
    "ипотек",
)

GREETING_WORDS = (
    "привет",
    "хай",
    "здарова",
    "здравствуй",
    "здравствуйте",
    "добрый день",
    "доброе утро",
    "добрый вечер",
    "ку",
    "хелло",
    "хеллоу",
    "приветствую",
    "салют",
    "бонжур",
    "хола",
)

# Carousel of fun replies when the bot is greeted
_MENTION_REPLIES = itertools.cycle([
    "Привет, сосед! 👋 Чем могу помочь по ЖК?",
    "О, меня упомянули! Я весь внимание 🤖",
    "Здравствуй! Спроси про шлагбаум или правила — отвечу. 😄",
    "Привет-привет! Что случилось в нашем ЖК?",
    "Здарова! Готов помочь с любым вопросом о жилом комплексе 🏠",
    "Йо! На связи, сосед. Что нужно узнать? 🙌",
    "Приветствую! Я тут как добрый сосед — всегда готов помочь 😊",
    "Здорово! Спрашивай — я знаю про наш ЖК почти всё! 🏡",
])

# Diverse replies when user asks by username and bot doesn't know the answer.
# Uses {username} placeholder for personalization.
_UNKNOWN_ANSWER_REPLIES = [
    "{username}, хороший вопрос! К сожалению, у меня нет точного ответа. Попробуй спросить в чате у соседей или обратиться в УК 🏢",
    "Ой, {username}, тут я пас 😅 Но могу помочь с вопросами про шлагбаум, правила, парковку — спрашивай!",
    "{username}, признаюсь — не знаю ответа на этот вопрос. Зато отлично разбираюсь в правилах ЖК! Может, что-то по этой теме? 😊",
    "Хм, {username}, это за пределами моих знаний. Рекомендую написать в топик обращений или позвонить в УК — они точно помогут! 📞",
    "{username}, увы, не могу ответить на это. Но если нужно узнать про домофон, парковку или мусор — я твой бот! 🤖",
    "Не уверен, что знаю ответ, {username}. Давай лучше спрошу у соседей в чате? А пока — могу рассказать про правила ЖК!",
    "{username}, такого в моей базе нет 🤔 Но я постоянно учусь! Попробуй задать вопрос иначе или спроси про жизнь в ЖК.",
    "Эх, {username}, поймал меня! Этого я не знаю. Но по вопросам ЖК — обращайся, тут я профи 💪",
]

_unknown_reply_counter = itertools.count()


def _next_mention_reply() -> str:
    return next(_MENTION_REPLIES)


def get_unknown_answer_reply(username: str | None = None) -> str:
    """Return a diverse reply when the bot doesn't know the answer.

    Cycles through _UNKNOWN_ANSWER_REPLIES with the user's display name
    inserted for personalization. If username is not provided, uses 'сосед'.
    """
    display_name = username or "сосед"
    idx = next(_unknown_reply_counter) % len(_UNKNOWN_ANSWER_REPLIES)
    return _UNKNOWN_ANSWER_REPLIES[idx].format(username=display_name)


def is_greeting(text: str) -> bool:
    """Return True if *text* contains a greeting word."""
    lowered = text.lower()
    return any(w in lowered for w in GREETING_WORDS)


def is_assistant_topic_allowed(text: str) -> bool:
    """Return True if text is relevant to the residential complex."""
    lowered = text.lower()
    return any(kw in lowered for kw in _ALLOWED_ASSISTANT_TOPICS)


def is_forbidden_topic(text: str) -> bool:
    """Return True if text touches explicitly forbidden topics."""
    lowered = text.lower()
    return any(kw in lowered for kw in _FORBIDDEN_ASSISTANT_TOPICS)


# ---------------------------------------------------------------------------
# Bot-name mention filter helpers
# ---------------------------------------------------------------------------

def _is_bot_name_called(text: str, bot_names: list[str]) -> bool:
    """Return True if any of *bot_names* is mentioned in *text*.

    Fix (Task 3): the original code used rf'(?<!\\\\w)...' which in Python
    produced a literal backslash-w instead of a word-boundary assertion.
    The fix uses a proper raw string with (?<![\\w]) boundaries.
    """
    text_lower = text.lower()
    for name in bot_names:
        # Correct word-boundary pattern using raw string
        boundary_pattern = r"(?<![" + r"\w" + r"])" + re.escape(name.casefold()) + r"(?![" + r"\w" + r"])"
        if re.search(boundary_pattern, text_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# Moderation prompt
# ---------------------------------------------------------------------------

_MODERATION_SYSTEM_PROMPT = """\
Ты — AI-модератор чата жилого комплекса (ЖК). Участники — соседи, общение преимущественно на русском языке.

Твоя задача: проанализировать сообщение и вернуть JSON-объект со следующими полями:
- violation_type: строка ("profanity" | "aggression" | "spam" | "forbidden_link" | "offtopic" | "none")
- severity: число от 0 до 3 (0 — нет нарушения, 1 — лёгкое, 2 — среднее, 3 — тяжёлое)
- confidence: число от 0.0 до 1.0
- action: строка ("none" | "warn" | "delete" | "mute_1h" | "mute_24h" | "ban")

Правила определения severity:
- 0: нет нарушения, технический вопрос, жалоба без агрессии
- 1: лёгкое нарушение — грубость без мата, офтоп
- 2: среднее — мат без агрессии, ссылки не по теме
- 3: тяжёлое — угрозы, мат с агрессией, спам, доксинг

Правила действий:
- severity 0 → action: "none"
- severity 1 → action: "warn"
- severity 2 → action: "delete" (или "warn" если сомневаешься)
- severity 3 → action: "mute_24h" (первый раз), "ban" (повторно)

Примеры замаскированного мата (считается нарушением severity 3):
- "x*й", "х*й", "xуй", "хуй", "хуй", "blyad", "пи3да", "п*зда" → мат
- "bl***", "п***ц", "е*ать" → мат

Слова-исключения (НЕ мат):
- "хлеб", "тебя", "небо", "сукно", "бляха-муха", "рыбак", "грибы"

Контекст ЖК: жалобы на соседей, вопросы про шлагбаум, правила, управляющую компанию — это нормальные сообщения (severity 0 или 1 без агрессии).

Верни ТОЛЬКО JSON без дополнительного текста.
"""

# ---------------------------------------------------------------------------
# Assistant system prompt
# ---------------------------------------------------------------------------

_ASSISTANT_SYSTEM_PROMPT = """\
Ты — AlexBot, дружелюбный сосед-помощник в жилом комплексе. Представь, что ты самый \
отзывчивый жилец в доме, который всё знает про ЖК и всегда рад помочь.

Твоя личность:
- Ты общаешься как добрый сосед, а не как робот или чиновник
- Используй простой разговорный язык, без канцелярита и бюрократизма
- Можешь шутить, но в меру — главное быть полезным
- Обращайся к жильцам на «ты», если они не попросили иначе

Твои задачи:
- Отвечать на вопросы о жизни в ЖК: правила, шлагбаум, парковка, мусор, лифт, \
домофон, детская площадка, животные, шум, ремонт, УК, охрана
- Давать краткие и конкретные ответы (2-4 предложения), с практическими советами
- Если знаешь ответ из базы знаний — используй эту информацию
- Если не уверен — честно скажи и подскажи, к кому обратиться (УК, администратор, чат)
- На приветствия отвечай тепло и по-соседски

Правила:
- НЕ давай юридических советов по судам, адвокатам, законодательству вне ЖК
- Правила ЖК — это НЕ юридический вопрос, отвечай на них свободно
- Жалобы на соседей в контексте ЖК — отвечай и помогай найти решение
- НЕ обсуждай политику, религию, финансовые инвестиции
- Если вопрос не по теме ЖК — мягко переведи разговор обратно к темам ЖК

Стиль: тёплый, дружелюбный, по-соседски, с лёгким юмором, всегда по делу.
"""


# ---------------------------------------------------------------------------
# OpenRouter provider
# ---------------------------------------------------------------------------

class OpenRouterProvider:
    """Async client for the OpenRouter AI API."""

    def __init__(self) -> None:
        self._base_url = settings.openrouter_base_url.rstrip("/")
        self._api_key = settings.openrouter_api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AlexBot",
            "X-Title": "AlexBot",
        }

    async def _chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        chat_id: int = 0,
    ) -> tuple[str, dict[str, Any]]:
        """Call OpenRouter chat completions and return (content, raw_response)."""
        payload = {
            "model": model or settings.ai_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = f"{self._base_url}/chat/completions"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self._headers, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        content = data["choices"][0]["message"]["content"]
        return content, data

    async def moderate_message(
        self,
        text: str,
        *,
        chat_id: int = 0,
    ) -> dict[str, Any]:
        """Return a moderation verdict dict for *text*.

        Falls back to a local rule-based check if the API call fails.
        """
        try:
            content, _ = await self._chat_completion(
                [
                    {"role": "system", "content": _MODERATION_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                model=settings.ai_moderation_model,
                temperature=0.1,
                max_tokens=200,
                chat_id=chat_id,
            )
            return json.loads(content)
        except Exception as exc:
            logger.warning("OpenRouter moderation failed: %s; using local fallback", exc)
            return _local_moderation_fallback(text)

    async def assistant_reply(
        self,
        prompt: str,
        context: list[dict[str, str]] | None = None,
        *,
        chat_id: int = 0,
        username: str | None = None,
    ) -> str:
        """Generate an assistant reply for *prompt*.

        Fix (Task 4): greetings now return a fun reply without requiring a ЖК
        topic keyword. Off-topic messages get a friendly redirect rather than a
        hard refusal.

        If RAG is enabled (settings.ai_feature_rag), relevant knowledge-base
        fragments are injected into the system prompt before calling the LLM.

        *username* is used for personalizing fallback replies when the bot
        doesn't know the answer.
        """
        safe_prompt = prompt.strip()

        # 1. Check forbidden topics first
        if is_forbidden_topic(safe_prompt):
            return (
                "Это за пределами моей компетенции. "
                "По юридическим вопросам обратитесь к специалисту. "
                "Но если есть вопрос по ЖК — спрашивай!"
            )

        # 2. Handle greetings — return carousel reply (no topic check needed)
        if is_greeting(safe_prompt):
            return _next_mention_reply()

        # 3. If off-topic — diverse personalized redirect
        if not is_assistant_topic_allowed(safe_prompt):
            return get_unknown_answer_reply(username)

        # 4. If AI is disabled, use local reply builder for ЖК topics
        if not self._api_key:
            return build_local_assistant_reply(safe_prompt)

        # 5. Build system prompt, optionally injecting RAG context
        system = _ASSISTANT_SYSTEM_PROMPT
        if settings.ai_feature_rag:
            try:
                from app.services.rag import search_rag, format_rag_context
                rag_results = search_rag(safe_prompt, top_k=3)
                rag_text = format_rag_context(rag_results)
                if rag_text:
                    system += f"\n\nБаза знаний ЖК:\n{rag_text}"
            except Exception as exc:
                logger.warning("RAG search failed: %s", exc)

        # 6. Call LLM
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if context:
            messages.extend(context)
        messages.append({"role": "user", "content": safe_prompt})

        try:
            content, _ = await self._chat_completion(
                messages, chat_id=chat_id
            )
            return content
        except Exception as exc:
            logger.error("OpenRouter assistant call failed: %s", exc)
            return build_local_assistant_reply(safe_prompt)


def build_local_assistant_reply(prompt: str) -> str:
    """Simple rule-based fallback reply when AI is unavailable."""
    lowered = prompt.lower()
    if "шлагбаум" in lowered or "ворот" in lowered or "пропуск" in lowered:
        return "Шлагбаум работает по карточке доступа. За новой карточкой — к администратору. Гости звонят через домофон! 🚗"
    if "правил" in lowered:
        return "Правила ЖК закреплены в топике #правила. Загляни туда!"
    if "сосед" in lowered:
        return "Споры с соседями лучше обсуждать в чате или обратиться в УК."
    if "парковк" in lowered or "въезд" in lowered or "машин" in lowered or "стоянк" in lowered:
        return "Гостевые места — у въезда (до 3 часов). Резидентные закреплены за собственниками. Подробности — у администратора 🅿️"
    if "мусор" in lowered or "контейнер" in lowered or "помойк" in lowered:
        return "Мусор вывозят ежедневно с 7:00 до 9:00. Крупногабаритный — по заявке в УК (среды). Контейнеры у подъездов 1 и 4 🗑️"
    if "домофон" in lowered or "ключ" in lowered:
        return "При проблемах с домофоном — заявка в УК. Замена ключа — 500 руб у администратора 🔑"
    if "лифт" in lowered:
        return "Обслуживание лифтов — по понедельникам 10:00-12:00. Застрял? Жми кнопку вызова или звони диспетчеру! 🛗"
    if "шум" in lowered or "тишин" in lowered or "громк" in lowered or "сверл" in lowered:
        return "Тишина: с 23:00 до 7:00 в будни, до 10:00 в выходные. Ремонт: пн-сб 9:00-19:00. Нарушения — в УК 🔇"
    if "собак" in lowered or "кошк" in lowered or "животн" in lowered or "питом" in lowered:
        return "Выгул собак — на площадке. В подъезде — поводок + намордник. Убирайте за питомцем! 🐕"
    if "площадк" in lowered or "детск" in lowered:
        return "Детская площадка: 8:00-21:00. Дети до 7 лет — с родителями. Сломалось что-то? Пиши в УК! 🎡"
    if "охран" in lowered or "консьерж" in lowered or "камер" in lowered:
        return "Территория под видеонаблюдением, консьерж — круглосуточно. Что-то подозрительное? Звони на пост! 🛡️"
    if "управляющ" in lowered or "ук " in lowered or "заявк" in lowered or "жалоб" in lowered:
        return "УК работает пн-пт 9:00-18:00. Аварийка — круглосуточно. Заявки — через приложение, телефон или чат 📋"
    if "курьер" in lowered or "доставк" in lowered or "посылк" in lowered:
        return "Курьеры проходят по звонку через домофон. Постаматы — у подъезда 2. Крупные доставки — согласуй с консьержем 📦"
    if "ремонт" in lowered or "перепланировк" in lowered:
        return "Ремонт: пн-сб 9:00-19:00, воскресенье — запрещено. Перепланировка — только с согласованием УК! 🔨"
    return "Напиши вопрос подробнее — постараюсь помочь! Я знаю всё про наш ЖК: шлагбаум, парковку, правила, соседей и многое другое 😊"


def _local_moderation_fallback(text: str) -> dict[str, Any]:
    """Rule-based moderation used when the API is unavailable."""
    if detect_profanity(text):
        return {
            "violation_type": "profanity",
            "severity": 3,
            "confidence": 0.85,
            "action": "delete",
        }
    return {
        "violation_type": "none",
        "severity": 0,
        "confidence": 0.9,
        "action": "none",
    }
