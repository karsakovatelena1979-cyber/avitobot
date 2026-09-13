"""Конфигурация бота — все переменные окружения и константы."""

import os
from pathlib import Path


# === ОБЯЗАТЕЛЬНЫЕ ПЕРЕМЕННЫЕ ===
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# === БАЗА ДАННЫХ ===
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "/data/bot.db")

# === ЛИМИТЫ ===
FREE_DAILY_CHECKS: int = 3
SUBSCRIPTION_PRICE_RUB: int = 100
SUBSCRIPTION_PRICE_STARS: int = 100  # Telegram Stars (XTR)
SUBSCRIPTION_MONTHS: int = 1

# === AI ===
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL: str = "google/gemini-2.0-flash-exp:free"
AI_MAX_TOKENS: int = 1000
AI_TIMEOUT: int = 60  # секунды

# === ПАРСИНГ ===
PARSER_TIMEOUT: int = 30  # секунды
PARSER_DELAY_MIN: float = 1.0  # секунды — минимальная задержка перед запросом
PARSER_DELAY_MAX: float = 3.0  # секунды — максимальная задержка
MAX_PHOTOS: int = 3  # сколько фото отправлять в AI

# === ПРОВЕРКА ===
CHECK_PROCESSING_MIN: int = 10  # секунды — минимальное время обработки (для UX)
CHECK_PROCESSING_MAX: int = 15  # секунды — максимальное время

# === ПАПКА ДЛЯ БД (создаём если нет) ===
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
