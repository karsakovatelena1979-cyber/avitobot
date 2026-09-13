"""Админ-панель: статистика, рассылка, список подписчиков."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import database
from config import ADMIN_ID
from keyboards.inline import admin_keyboard
from utils.texts import (
    ADMIN_ACCESS_DENIED,
    ADMIN_BROADCAST_CANCELLED,
    ADMIN_BROADCAST_DONE,
    ADMIN_BROADCAST_PROMPT,
    ADMIN_PANEL,
    ADMIN_STATS_7_DAYS,
    ADMIN_SUBSCRIBERS_EMPTY,
    ADMIN_SUBSCRIBERS_LIST,
)

logger = logging.getLogger(__name__)
router = Router()


class BroadcastState(StatesGroup):
    waiting_text = State()


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Админ-панель."""
    if not _is_admin(message.from_user.id):
        await message.answer(ADMIN_ACCESS_DENIED)
        return

    total = await database.get_total_users()
    today = await database.get_new_users_today()
    subs = await database.get_active_subscriptions()
    checks = await database.get_checks_today()
    sales = await database.get_total_sales()

    await message.answer(
        ADMIN_PANEL.format(
            total=total,
            today=today,
            subs=subs,
            checks=checks,
            sales=sales,
        ),
        reply_markup=admin_keyboard(),
    )


@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало рассылки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.message.edit_text(ADMIN_BROADCAST_PROMPT)
    await state.set_state(BroadcastState.waiting_text)
    await callback.answer()


@router.message(BroadcastState.waiting_text, F.text == "/cancel")
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    """Отмена рассылки."""
    await state.clear()
    await message.answer(ADMIN_BROADCAST_CANCELLED)


@router.message(BroadcastState.waiting_text)
async def process_broadcast(message: Message, state: FSMContext) -> None:
    """Отправка рассылки всем пользователям."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    text = message.text
    await state.clear()

    user_ids = await database.get_all_user_ids()
    success = 0
    failed = 0

    status_msg = await message.answer("📤 Рассылаю сообщения...")

    for uid in user_ids:
        try:
            await message.bot.send_message(uid, text)
            success += 1
        except Exception as e:
            logger.warning("Не удалось отправить %s: %s", uid, e)
            failed += 1

    await status_msg.edit_text(
        ADMIN_BROADCAST_DONE.format(success=success, failed=failed)
    )
    logger.info("Рассылка: доставлено=%d, не доставлено=%d", success, failed)


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery) -> None:
    """Статистика за 7 дней."""
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return

    stats = await database.get_stats_7_days()
    rows = []
    total_sales = 0
    total_revenue = 0

    for s in stats:
        day = s["day"][5:]  # MM-DD
        rows.append(
            f"📅 {day}: 👥 {s['new_users']} | 💳 {s['sales']} | 💰 {s['revenue']}₽"
        )
        total_sales += s["sales"]
        total_revenue += s["revenue"]

    await callback.message.edit_text(
        ADMIN_STATS_7_DAYS.format(
            rows="\n".join(rows),
            total_sales=total_sales,
            total_revenue=total_revenue,
        ),
        reply_markup=admin_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_subscribers")
async def cb_admin_subscribers(callback: CallbackQuery) -> None:
    """Список активных подписчиков."""
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return

    subscribers = await database.get_subscribers_list()
    if not subscribers:
        await callback.message.edit_text(
            ADMIN_SUBSCRIBERS_EMPTY, reply_markup=admin_keyboard()
        )
        await callback.answer()
        return

    rows = []
    for s in subscribers[:50]:
        name = s["first_name"] or s["username"] or str(s["user_id"])
        expiry = s["sub_expires_at"][:10] if s["sub_expires_at"] else "?"
        rows.append(f"• {name} (ID: {s['user_id']}) — до {expiry}")

    await callback.message.edit_text(
        ADMIN_SUBSCRIBERS_LIST.format(count=len(subscribers), rows="\n".join(rows)),
        reply_markup=admin_keyboard(),
    )
    await callback.answer()
