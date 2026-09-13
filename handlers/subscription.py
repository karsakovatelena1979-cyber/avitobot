"""Подписка: покупка через Telegram Stars, статус."""

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

import database
from config import (
    ADMIN_ID,
    SUBSCRIPTION_MONTHS,
    SUBSCRIPTION_PRICE_STARS,
)
from keyboards.inline import pay_stars_keyboard, start_keyboard, subscribe_keyboard
from utils.texts import (
    INVOICE_DESCRIPTION,
    INVOICE_PAYLOAD,
    INVOICE_TITLE,
    PAYMENT_FAILED,
    PAYMENT_SUCCESS,
    SUBSCRIBE_STUB_CRYPTO,
    SUBSCRIBE_STUB_SBP,
    SUBSCRIBE_TEXT,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_ALREADY_ACTIVE,
)

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "/subscribe")
async def cmd_subscribe(message: Message) -> None:
    """Команда /subscribe."""
    await _show_subscribe(message)


@router.callback_query(F.data == "open_subscribe")
async def cb_open_subscribe(callback: CallbackQuery) -> None:
    """Открыть меню подписки."""
    await _show_subscribe(callback.message)
    await callback.answer()


async def _show_subscribe(message: Message) -> None:
    """Показывает меню выбора способа оплаты."""
    user_id = message.from_user.id
    if await database.is_subscription_active(user_id):
        user = await database.get_user(user_id)
        try:
            expiry = datetime.fromisoformat(user["sub_expires_at"])
            date_str = expiry.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            date_str = "?"
        await message.answer(
            SUBSCRIPTION_ALREADY_ACTIVE.format(date=date_str),
            reply_markup=start_keyboard(),
        )
        return
    await message.answer(SUBSCRIBE_TEXT, reply_markup=subscribe_keyboard())


@router.callback_query(F.data == "pay_sbp")
async def cb_pay_sbp(callback: CallbackQuery) -> None:
    await callback.message.edit_text(SUBSCRIBE_STUB_SBP, reply_markup=subscribe_keyboard())
    await callback.answer()


@router.callback_query(F.data == "pay_crypto")
async def cb_pay_crypto(callback: CallbackQuery) -> None:
    await callback.message.edit_text(SUBSCRIBE_STUB_CRYPTO, reply_markup=subscribe_keyboard())
    await callback.answer()


@router.callback_query(F.data == "pay_stars")
async def cb_pay_stars(callback: CallbackQuery) -> None:
    """Показывает кнопку оплаты Stars."""
    await callback.message.edit_text(
        f"⭐ Оплата Telegram Stars\n\nПодписка на {SUBSCRIPTION_MONTHS} мес — {SUBSCRIPTION_PRICE_STARS} Stars",
        reply_markup=pay_stars_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "pay_stars_confirm")
async def cb_pay_stars_confirm(callback: CallbackQuery) -> None:
    """Отправляет инвойс Telegram Stars."""
    prices = [LabeledPrice(label="Подписка 1 месяц", amount=SUBSCRIPTION_PRICE_STARS)]
    await callback.message.answer_invoice(
        title=INVOICE_TITLE,
        description=INVOICE_DESCRIPTION,
        payload=INVOICE_PAYLOAD,
        currency="XTR",
        prices=prices,
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    """Подтверждение оплаты."""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    """Успешная оплата — активируем подписку."""
    payment = message.successful_payment
    user_id = message.from_user.id

    try:
        expiry = await database.activate_subscription(user_id, SUBSCRIPTION_MONTHS)
        await database.add_payment(
            user_id=user_id,
            amount=payment.total_amount,
            method="stars",
            months=SUBSCRIPTION_MONTHS,
        )
        date_str = expiry.strftime("%d.%m.%Y")
        await message.answer(
            PAYMENT_SUCCESS.format(date=date_str),
            reply_markup=start_keyboard(),
        )
        logger.info("Подписка активирована: user_id=%s до %s", user_id, date_str)

        if ADMIN_ID:
            try:
                await message.bot.send_message(
                    ADMIN_ID,
                    f"💰 Новая продажа!\nПользователь: {user_id} (@{message.from_user.username or 'нет'})\nСумма: {payment.total_amount} Stars",
                )
            except Exception as e:
                logger.warning("Не удалось уведомить админа: %s", e)
    except Exception as e:
        logger.exception("Ошибка активации подписки: %s", e)
        await message.answer(PAYMENT_FAILED)
