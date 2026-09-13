"""Хендлеры /start, /help, /status."""

import logging
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

import database
from keyboards.inline import start_keyboard
from utils.texts import (
    ADMIN_ACCESS_DENIED,
    HELP_TEXT,
    START_TEXT,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_FREE,
)

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие и онбординг."""
    await database.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await message.answer(START_TEXT, reply_markup=start_keyboard())
    logger.info("Новый пользователь: %s", message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Справка."""
    await message.answer(HELP_TEXT)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Статус пользователя: подписка и остаток проверок."""
    await _send_status(message)


@router.callback_query(lambda c: c.data == "my_status")
async def cb_my_status(callback: CallbackQuery) -> None:
    """Статус по кнопке."""
    await _send_status(callback.message)
    await callback.answer()


@router.callback_query(lambda c: c.data == "back_to_start")
async def cb_back_to_start(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    await callback.message.edit_text(START_TEXT, reply_markup=start_keyboard())
    await callback.answer()


async def _send_status(message: Message) -> None:
    """Формирует и отправляет статус пользователя."""
    user_id = message.from_user.id
    await database.reset_daily_checks_if_needed(user_id)
    user = await database.get_user(user_id)

    if not user:
        await message.answer(START_TEXT, reply_markup=start_keyboard())
        return

    is_active = await database.is_subscription_active(user_id)
    if is_active:
        try:
            expiry = datetime.fromisoformat(user["sub_expires_at"])
            date_str = expiry.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            date_str = "?"
        await message.answer(
            SUBSCRIPTION_STATUS_ACTIVE.format(date=date_str),
            reply_markup=start_keyboard(),
        )
    else:
        from config import FREE_DAILY_CHECKS
        used = user["checks_today"] or 0
        remaining = max(0, FREE_DAILY_CHECKS - used)
        await message.answer(
            SUBSCRIPTION_STATUS_FREE.format(
                used=used,
                limit=FREE_DAILY_CHECKS,
                remaining=remaining,
            ),
            reply_markup=start_keyboard(),
        )
