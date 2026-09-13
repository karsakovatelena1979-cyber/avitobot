"""Middleware для проверки лимитов пользователя.

Проверяет подписку и дневной лимит проверок.
Логика проверки — только здесь, не дублируется в хендлерах.
"""

import logging
from datetime import date

from aiogram import BaseMiddleware
from aiogram.types import Message

import database
from config import FREE_DAILY_CHECKS
from utils.texts import LIMIT_REACHED

logger = logging.getLogger(__name__)


class SubscriptionMiddleware(BaseMiddleware):
    """Проверяет лимит проверок перед обработкой сообщения со ссылкой."""

    async def __call__(self, handler, event, data):
        # Работаем только с сообщениями
        if not isinstance(event, Message):
            return await handler(event, data)

        # Проверяем только сообщения со ссылками Авито (простая эвристика)
        text = event.text or ""
        if "avito.ru" not in text:
            return await handler(event, data)

        user_id = event.from_user.id

        # Добавляем пользователя если новый
        await database.add_user(
            user_id=user_id,
            username=event.from_user.username,
            first_name=event.from_user.first_name,
        )

        # Если подписка активна — пропускаем
        if await database.is_subscription_active(user_id):
            return await handler(event, data)

        # Сбрасываем счётчик если новый день
        await database.reset_daily_checks_if_needed(user_id)

        user = await database.get_user(user_id)
        checks_today = user["checks_today"] if user else 0

        if checks_today >= FREE_DAILY_CHECKS:
            logger.info("Лимит исчерпан для user_id=%s", user_id)
            await event.answer(LIMIT_REACHED)
            return  # НЕ вызываем handler

        return await handler(event, data)
