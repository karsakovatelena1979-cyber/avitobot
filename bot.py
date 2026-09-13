"""Точка входа — запуск polling."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database
from handlers import admin, check, start, subscription
from middlewares.subscription import SubscriptionMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Инициализация и запуск бота."""
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан!")
    if not config.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY не задан!")

    await database.init_db()
    logger.info("База данных готова")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(SubscriptionMiddleware())

    dp.include_router(start.router)
    dp.include_router(check.router)
    dp.include_router(subscription.router)
    dp.include_router(admin.router)

    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
