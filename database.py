"""База данных SQLite через aiosqlite."""

import logging
import os
from datetime import date, datetime, timedelta

import aiosqlite

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Создаём таблицы если не существуют. Папку тоже создаём."""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_subscribed INTEGER DEFAULT 0,
                sub_expires_at TIMESTAMP,
                checks_today   INTEGER DEFAULT 0,
                last_check_date DATE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER,
                amount   INTEGER,
                method   TEXT,
                paid_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                months   INTEGER DEFAULT 1
            )
        """)
        await db.commit()
    logger.info("База данных инициализирована: %s", DATABASE_PATH)


async def add_user(user_id: int, username: str | None, first_name: str | None) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (user_id, username, first_name))
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def is_subscription_active(user_id: int) -> bool:
    user = await get_user(user_id)
    if not user or not user["is_subscribed"]:
        return False
    if not user["sub_expires_at"]:
        return False
    try:
        expires = datetime.fromisoformat(user["sub_expires_at"])
        return expires > datetime.utcnow()
    except (ValueError, TypeError):
        return False


async def activate_subscription(user_id: int, months: int = 1) -> datetime:
    expires = datetime.utcnow() + timedelta(days=30 * months)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            UPDATE users
            SET is_subscribed = 1, sub_expires_at = ?
            WHERE user_id = ?
        """, (expires.isoformat(), user_id))
        await db.commit()
    return expires


async def add_payment(user_id: int, amount: int, method: str, months: int = 1) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO payments (user_id, amount, method, months)
            VALUES (?, ?, ?, ?)
        """, (user_id, amount, method, months))
        await db.commit()


async def reset_daily_checks_if_needed(user_id: int) -> None:
    user = await get_user(user_id)
    if not user:
        return
    today = date.today().isoformat()
    if user["last_check_date"] != today:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE users SET checks_today = 0, last_check_date = ?
                WHERE user_id = ?
            """, (today, user_id))
            await db.commit()


async def increment_checks(user_id: int) -> None:
    today = date.today().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            UPDATE users
            SET checks_today = checks_today + 1, last_check_date = ?
            WHERE user_id = ?
        """, (today, user_id))
        await db.commit()


async def get_stats() -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        today = date.today().isoformat()

        async with db.execute("SELECT COUNT(*) as cnt FROM users") as cur:
            total = (await cur.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE DATE(created_at) = ?", (today,)
        ) as cur:
            today_users = (await cur.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE is_subscribed = 1 AND sub_expires_at > datetime('now')"
        ) as cur:
            active_subs = (await cur.fetchone())["cnt"]

        async with db.execute(
            "SELECT COALESCE(SUM(checks_today), 0) as cnt FROM users WHERE last_check_date = ?", (today,)
        ) as cur:
            checks_today = (await cur.fetchone())["cnt"]

        async with db.execute("SELECT COUNT(*) as cnt FROM payments") as cur:
            total_sales = (await cur.fetchone())["cnt"]

        return {
            "total": total,
            "today": today_users,
            "subs": active_subs,
            "checks": checks_today,
            "sales": total_sales,
        }


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
            return [row[0] for row in rows]


async def get_active_subscribers() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, username, first_name, sub_expires_at
            FROM users
            WHERE is_subscribed = 1 AND sub_expires_at > datetime('now')
            ORDER BY sub_expires_at DESC
        """) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_stats_7_days() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                DATE(paid_at) as day,
                COUNT(*) as sales,
                SUM(amount) as revenue
            FROM payments
            WHERE paid_at >= datetime('now', '-7 days')
            GROUP BY DATE(paid_at)
            ORDER BY day DESC
        """) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
