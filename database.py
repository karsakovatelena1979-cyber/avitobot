"""Работа с базой данных SQLite через aiosqlite.

КРИТИЧНО: файл БД хранится на PERSISTENT volume (/data/bot.db),
поэтому данные НЕ сбрасываются при деплое/рестарте.
"""

import logging
from datetime import datetime, date, timedelta

import aiosqlite

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Создаёт таблицы если не существуют. НИКОГДА не удаляет данные."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_subscribed INTEGER DEFAULT 0,
                sub_expires_at TIMESTAMP,
                checks_today INTEGER DEFAULT 0,
                last_check_date DATE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                method TEXT,
                paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                months INTEGER DEFAULT 1
            )
        """)
        await db.commit()
    logger.info("База данных инициализирована: %s", DATABASE_PATH)


async def add_user(user_id: int, username: str | None, first_name: str | None) -> None:
    """Добавляет пользователя если его нет, иначе обновляет имя."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    """Возвращает данные пользователя или None."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def reset_daily_checks_if_needed(user_id: int) -> None:
    """Сбрасывает счётчик проверок если наступил новый день."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            UPDATE users
            SET checks_today = 0, last_check_date = ?
            WHERE user_id = ? AND last_check_date != ?
        """, (today, user_id, today))
        await db.commit()


async def increment_checks(user_id: int) -> int:
    """Увеличивает счётчик проверок за сегодня. Возвращает новое значение."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Если last_check_date не сегодня — сначала сбрасываем
        await db.execute("""
            UPDATE users
            SET checks_today = 0, last_check_date = ?
            WHERE user_id = ? AND last_check_date != ?
        """, (today, user_id, today))
        await db.execute("""
            UPDATE users
            SET checks_today = checks_today + 1, last_check_date = ?
            WHERE user_id = ?
        """, (today, user_id))
        await db.commit()
        async with db.execute(
            "SELECT checks_today FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def activate_subscription(user_id: int, months: int = 1) -> datetime:
    """Активирует/продлевает подписку. Возвращает дату окончания."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT sub_expires_at FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

        now = datetime.now()
        if row and row["sub_expires_at"]:
            try:
                current_expiry = datetime.fromisoformat(row["sub_expires_at"])
            except (ValueError, TypeError):
                current_expiry = now
            base_date = max(current_expiry, now)
        else:
            base_date = now

        new_expiry = base_date + timedelta(days=30 * months)
        await db.execute("""
            UPDATE users
            SET is_subscribed = 1, sub_expires_at = ?
            WHERE user_id = ?
        """, (new_expiry.isoformat(), user_id))
        await db.commit()
        return new_expiry


async def add_payment(user_id: int, amount: int, method: str, months: int = 1) -> None:
    """Записывает платёж в историю."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO payments (user_id, amount, method, months)
            VALUES (?, ?, ?, ?)
        """, (user_id, amount, method, months))
        await db.commit()


async def is_subscription_active(user_id: int) -> bool:
    """Проверяет активна ли подписка."""
    user = await get_user(user_id)
    if not user or not user["is_subscribed"]:
        return False
    if not user["sub_expires_at"]:
        return False
    try:
        expiry = datetime.fromisoformat(user["sub_expires_at"])
        return expiry > datetime.now()
    except (ValueError, TypeError):
        return False


# === СТАТИСТИКА ДЛЯ АДМИНКИ ===

async def get_total_users() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_new_users_today() -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE date(created_at) = ?", (today,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_active_subscriptions() -> int:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE is_subscribed = 1 AND sub_expires_at > ?",
            (now,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_checks_today() -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(checks_today), 0) FROM users WHERE last_check_date = ?",
            (today,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_total_sales() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM payments"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_subscribers_list() -> list[dict]:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, username, first_name, sub_expires_at
            FROM users
            WHERE is_subscribed = 1 AND sub_expires_at > ?
            ORDER BY sub_expires_at DESC
        """, (now,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_stats_7_days() -> list[dict]:
    """Статистика за последние 7 дней: новые пользователи и продажи по дням."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT date(created_at) as day, COUNT(*) as count
            FROM users
            WHERE created_at >= date('now', '-7 days')
            GROUP BY date(created_at)
            ORDER BY day
        """) as cursor:
            users_rows = await cursor.fetchall()
        async with db.execute("""
            SELECT date(paid_at) as day, COUNT(*) as count, COALESCE(SUM(amount), 0) as revenue
            FROM payments
            WHERE paid_at >= date('now', '-7 days')
            GROUP BY date(paid_at)
            ORDER BY day
        """) as cursor:
            payments_rows = await cursor.fetchall()

    users_by_day = {r["day"]: r["count"] for r in users_rows}
    payments_by_day = {r["day"]: (r["count"], r["revenue"]) for r in payments_rows}

    result = []
    for i in range(6, -1, -1):
        day = (date.today() - timedelta(days=i)).isoformat()
        p_count, p_revenue = payments_by_day.get(day, (0, 0))
        result.append({
            "day": day,
            "new_users": users_by_day.get(day, 0),
            "sales": p_count,
            "revenue": p_revenue,
        })
    return result
