"""Все inline-клавиатуры бота."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.texts import (
    BTN_ADMIN_BROADCAST,
    BTN_ADMIN_STATS,
    BTN_ADMIN_SUBSCRIBERS,
    BTN_BACK,
    BTN_CRYPTO,
    BTN_MY_STATUS,
    BTN_SBP,
    BTN_STARS,
    BTN_SUBSCRIBE,
)


def subscribe_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_STARS, callback_data="pay_stars")],
        [InlineKeyboardButton(text=BTN_SBP, callback_data="pay_sbp")],
        [InlineKeyboardButton(text=BTN_CRYPTO, callback_data="pay_crypto")],
        [InlineKeyboardButton(text=BTN_BACK, callback_data="back_to_start")],
    ])


def start_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура главного меню."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SUBSCRIBE, callback_data="open_subscribe")],
        [InlineKeyboardButton(text=BTN_MY_STATUS, callback_data="my_status")],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с одной кнопкой «Назад»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_BACK, callback_data="back_to_start")],
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура админ-панели."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_ADMIN_BROADCAST, callback_data="admin_broadcast")],
        [InlineKeyboardButton(text=BTN_ADMIN_STATS, callback_data="admin_stats")],
        [InlineKeyboardButton(text=BTN_ADMIN_SUBSCRIBERS, callback_data="admin_subscribers")],
    ])


def pay_stars_keyboard() -> InlineKeyboardMarkup:
    """Кнопка оплаты Stars."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Оплатить 100 Stars", callback_data="pay_stars_confirm")],
        [InlineKeyboardButton(text=BTN_BACK, callback_data="open_subscribe")],
    ])
