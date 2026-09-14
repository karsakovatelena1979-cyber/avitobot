"""Конфигурация бота — все переменные из env."""

import os

# Telegram
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))

# База данных
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "/data/bot.db")

# OpenRouter
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL: str = "openrouter/free"

# ScraperAPI
SCRAPER_API_KEY: str = os.getenv("SCRAPER_API_KEY", "")

# Парсер
MAX_PHOTOS: int = 3
PARSER_TIMEOUT: float = 30.0
PARSER_DELAY_MIN: float = 1.0
PARSER_DELAY_MAX: float = 3.0

# AI
AI_MAX_TOKENS: int = 1000
AI_TIMEOUT: float = 60.0

# Подписка
SUBSCRIPTION_PRICE_STARS: int = 100
SUBSCRIPTION_MONTHS: int = 1
FREE_CHECKS_PER_DAY: int = 3

# Invoice
INVOICE_TITLE: str = "Подписка AvitoChecker на 1 месяц"
INVOICE_DESCRIPTION: str = "Безлимитные проверки объявлений Авито с AI-анализом"
INVOICE_PAYLOAD: str = "subscription_1_month"

# UX
CHECK_PROCESSING_MIN: float = 1.0
CHECK_PROCESSING_MAX: float = 3.0
FREE_DAILY_CHECKS: int = 3
