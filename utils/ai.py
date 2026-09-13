"""Запросы к OpenRouter (совместим с OpenAI SDK).

Модель: google/gemini-2.0-flash-exp:free
Отправляет текст объявления + фото (base64) и получает вердикт.
"""

import base64
import logging

from openai import AsyncOpenAI

from config import (
    AI_MAX_TOKENS,
    AI_TIMEOUT,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
)
from utils.parser import AvitoListing

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Ты эксперт по оценке объявлений на Авито. Проанализируй это объявление и дай честный вердикт.

Объявление:
Название: {title}
Цена: {price}
Описание: {description}
Состояние: {condition}
Категория: {category}

Фото прилагаются.

Ответь строго в формате:
ВЕРДИКТ: [БРАТЬ / ОСТОРОЖНО / БЕЖАТЬ]
ПРИЧИНА: [2-3 предложения почему]
НА ЧТО ОБРАТИТЬ ВНИМАНИЕ: [2-3 конкретных пункта]
ЧЕСТНАЯ ЦЕНА: [твоя оценка справедливой цены или "цена адекватная"]"""


class AIError(Exception):
    """Ошибка при обращении к AI."""
    pass


def _build_prompt(listing: AvitoListing) -> str:
    return PROMPT_TEMPLATE.format(
        title=listing.title or "не указано",
        price=listing.price or "не указана",
        description=listing.description[:2000] or "нет описания",
        condition=listing.condition or "не указано",
        category=listing.category or "не указана",
    )


def _build_image_content(photos_base64: list[str]) -> list[dict]:
    """Формирует content-блоки с изображениями для API."""
    content = []
    for b64 in photos_base64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64}",
            },
        })
    return content


async def analyze_listing(listing: AvitoListing) -> str:
    """Отправляет объявление в AI и возвращает вердикт (текст)."""
    client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        timeout=AI_TIMEOUT,
    )

    prompt = _build_prompt(listing)
    image_content = _build_image_content(listing.photos_base64)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                *image_content,
            ],
        }
    ]

    try:
        response = await client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            max_tokens=AI_MAX_TOKENS,
        )
        verdict = response.choices[0].message.content
        if not verdict:
            raise AIError("Пустой ответ от AI")
        logger.info("AI вердикт получен (%d символов)", len(verdict))
        return verdict
    except Exception as e:
        logger.error("Ошибка AI: %s", e)
        raise AIError(str(e)) from e
