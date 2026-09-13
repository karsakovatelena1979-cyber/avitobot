"""Основная логика: парсинг Авито + AI-анализ."""

import asyncio
import logging
import random

from aiogram import Router
from aiogram.types import Message

import database
from config import CHECK_PROCESSING_MAX, CHECK_PROCESSING_MIN
from utils.ai import AIError, analyze_listing
from utils.parser import (
    AvitoBlockedError,
    AvitoNotFoundError,
    is_avito_url,
    parse_avito,
)
from utils.texts import (
    CHECK_ERROR_AI,
    CHECK_ERROR_BLOCKED,
    CHECK_ERROR_GENERIC,
    CHECK_ERROR_NOT_AVITO,
    CHECK_ERROR_NOT_FOUND,
    CHECK_PROCESSING,
)

logger = logging.getLogger(__name__)
router = Router()


def _format_verdict(verdict: str) -> str:
    text = verdict.strip()
    upper = text.upper()
    if "БРАТЬ" in upper and "БЕЖАТЬ" not in upper:
        if "✅" not in text:
            text = "✅ " + text
    elif "БЕЖАТЬ" in upper:
        if "🚫" not in text:
            text = "🚫 " + text
    elif "ОСТОРОЖНО" in upper:
        if "⚠️" not in text:
            text = "⚠️ " + text
    return text


@router.message(lambda m: m.text and "avito.ru" in m.text)
async def check_listing(message: Message) -> None:
    url = message.text.strip()

    if not is_avito_url(url):
        await message.answer(CHECK_ERROR_NOT_AVITO)
        return

    processing_msg = await message.answer(CHECK_PROCESSING)

    try:
        listing = await parse_avito(url)
    except AvitoBlockedError as e:
        logger.warning("Авито заблокировал: %s", e)
        await processing_msg.edit_text(CHECK_ERROR_BLOCKED)
        return
    except AvitoNotFoundError as e:
        logger.warning("Объявление не найдено: %s", e)
        await processing_msg.edit_text(CHECK_ERROR_NOT_FOUND)
        return
    except Exception as e:
        logger.exception("Ошибка парсинга: %s", e)
        await processing_msg.edit_text(
            f"😔 Не смог загрузить объявление.\n\n"
            f"Причина: <code>{type(e).__name__}: {str(e)[:200]}</code>\n\n"
            f"Попробуй через минуту или скинь текст объявления вручную."
        )
        return

    if not listing.title:
        logger.error("Пустой заголовок для %s", url)
        await processing_msg.edit_text(
            "🤔 Загрузил страницу, но не смог прочитать объявление.\n\n"
            "Скорее всего Авито показал капчу или изменил вёрстку.\n\n"
            "Скинь текст объявления вручную — название, цену и описание."
        )
        return

    wait_time = random.uniform(CHECK_PROCESSING_MIN, CHECK_PROCESSING_MAX) / 2
    await asyncio.sleep(wait_time)

    try:
        verdict = await analyze_listing(listing)
    except AIError as e:
        logger.error("Ошибка AI: %s", e)
        await processing_msg.edit_text(
            f"🛌 Объявление прочитал, но AI не ответил.\n\n"
            f"Причина: <code>{str(e)[:200]}</code>\n\n"
            f"Попробуй через пару минут."
        )
        return
    except Exception as e:
        logger.exception("Неизвестная ошибка AI: %s", e)
        await processing_msg.edit_text(CHECK_ERROR_AI)
        return

    await database.increment_checks(message.from_user.id)
    formatted = _format_verdict(verdict)
    await processing_msg.edit_text(formatted, parse_mode="HTML")
    logger.info("Вердикт отправлен user_id=%s", message.from_user.id)


@router.message(lambda m: m.text and m.text.startswith("http"))
async def wrong_link(message: Message) -> None:
    await message.answer(CHECK_ERROR_NOT_AVITO)
