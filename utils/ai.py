"""Запросы к OpenRouter с fallback между моделями."""

import logging

import httpx

from config import (
    AI_MAX_TOKENS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)
from utils.parser import AvitoListing

logger = logging.getLogger(__name__)

VISION_MODELS = [
    "qwen/qwen-2.5-vl-72b-instruct:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemini-2.0-flash-exp:free",
]

PROMPT_TEMPLATE = """Ты эксперт по оценке объявлений на Авито. Проанализируй это объявление и дай честный вердикт.

Объявление:
Название: {title}
Цена: {price}
Описание: {description}
Состояние: {condition}
Категория: {category}

Ответь строго в формате:
ВЕРДИКТ: [БРАТЬ / ОСТОРОЖНО / БЕЖАТЬ]
ПРИЧИНА: [2-3 предложения почему]
НА ЧТО ОБРАТИТЬ ВНИМАНИЕ: [2-3 конкретных пункта]
ЧЕСТНАЯ ЦЕНА: [твоя оценка справедливой цены или "цена адекватная"]"""


class AIError(Exception):
    pass


def _build_messages(listing: AvitoListing) -> list:
    prompt = PROMPT_TEMPLATE.format(
        title=listing.title or "не указано",
        price=listing.price or "не указана",
        description=(listing.description or "нет описания")[:2000],
        condition=listing.condition or "не указано",
        category=listing.category or "не указана",
    )
    content = [{"type": "text", "text": prompt}]
    for b64 in listing.photos_base64[:3]:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    return [{"role": "user", "content": content}]


async def analyze_listing(listing: AvitoListing) -> str:
    messages = _build_messages(listing)
    last_error = None

    for model in VISION_MODELS:
        try:
            logger.info("Пробуем модель: %s", model)
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://t.me/Radar_Avito_Bot",
                        "X-Title": "Avito Radar Bot",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": AI_MAX_TOKENS,
                    },
                )
                if resp.status_code == 429:
                    logger.warning("Лимит модели %s", model)
                    last_error = f"429 от {model}"
                    continue
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code} от {model}: {resp.text[:200]}"
                    continue
                data = resp.json()
                verdict = data["choices"][0]["message"]["content"]
                if not verdict or len(verdict) < 10:
                    last_error = f"Пустой ответ от {model}"
                    continue
                logger.info("Успех! Модель %s, %d символов", model, len(verdict))
                return verdict
        except Exception as e:
            logger.warning("Ошибка %s: %s", model, e)
            last_error = str(e)
            continue

    raise AIError(f"Все модели недоступны. Последняя ошибка: {last_error}")
