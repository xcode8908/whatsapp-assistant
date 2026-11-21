import os
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import aiosqlite
import asyncpg
from config import settings

class Database:
    def __init__(self):
        self.is_postgres = bool(settings.DATABASE_URL and settings.DATABASE_URL.startswith("postgres"))
        self.pg_pool: Optional[asyncpg.Pool] = None
        
        # Ensure SQLite data directory exists
        if not self.is_postgres:
            settings.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.sqlite_path = str(settings.SQLITE_PATH)

    async def init(self):
        """Initialize database connection and tables"""
        if self.is_postgres:
            self.pg_pool = await asyncpg.create_pool(dsn=settings.DATABASE_URL, min_size=1, max_size=5)
            await self._create_pg_tables()
        else:
            await self._create_sqlite_tables()

    async def _create_sqlite_tables(self):
        async with aiosqlite.connect(self.sqlite_path) as db:
            # Bot State
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            # Scheduled Messages
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    send_at INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending'
                )
            """)
            # Cooldown Tracking
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    chat_id TEXT PRIMARY KEY,
                    last_replied INTEGER NOT NULL
                )
            """)
            # Chat History for AI Context
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            # Initialize default state if not exists
            cursor = await db.execute("SELECT value FROM bot_state WHERE key = 'is_offline'")
            row = await cursor.fetchone()
            if not row:
                await db.execute("INSERT INTO bot_state (key, value) VALUES ('is_offline', 'false')")
                await db.execute("INSERT INTO bot_state (key, value) VALUES ('custom_message', '')")
            await db.commit()

    async def _create_pg_tables(self):
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id SERIAL PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    send_at BIGINT NOT NULL,
                    status TEXT DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS cooldowns (
                    chat_id TEXT PRIMARY KEY,
                    last_replied BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at BIGINT NOT NULL
                );
            """)
            # Check default state
            row = await conn.fetchrow("SELECT value FROM bot_state WHERE key = 'is_offline'")
            if not row:
                await conn.execute("INSERT INTO bot_state (key, value) VALUES ('is_offline', 'false') ON CONFLICT DO NOTHING")
                await conn.execute("INSERT INTO bot_state (key, value) VALUES ('custom_message', '') ON CONFLICT DO NOTHING")

    # ==========================================
    # Bot State Methods (Online/Offline/Custom)
    # ==========================================
    async def is_offline_mode(self) -> bool:
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT value FROM bot_state WHERE key = 'is_offline'")
                return row['value'].lower() == 'true' if row else False
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cursor = await db.execute("SELECT value FROM bot_state WHERE key = 'is_offline'")
                row = await cursor.fetchone()
                return row[0].lower() == 'true' if row else False

    async def set_offline_mode(self, is_offline: bool):
        val = 'true' if is_offline else 'false'
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO bot_state (key, value) VALUES ('is_offline', $1)
                    ON CONFLICT (key) DO UPDATE SET value = $1
                """, val)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("""
                    INSERT INTO bot_state (key, value) VALUES ('is_offline', ?)
                    ON CONFLICT (key) DO UPDATE SET value = ?
                """, (val, val))
                await db.commit()

    async def get_custom_message(self) -> Optional[str]:
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT value FROM bot_state WHERE key = 'custom_message'")
                return row['value'] if row and row['value'] else None
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cursor = await db.execute("SELECT value FROM bot_state WHERE key = 'custom_message'")
                row = await cursor.fetchone()
                return row[0] if row and row[0] else None

    async def set_custom_message(self, message: Optional[str]):
        val = message.strip() if message else ""
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO bot_state (key, value) VALUES ('custom_message', $1)
                    ON CONFLICT (key) DO UPDATE SET value = $1
                """, val)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("""
                    INSERT INTO bot_state (key, value) VALUES ('custom_message', ?)
                    ON CONFLICT (key) DO UPDATE SET value = ?
                """, (val, val))
                await db.commit()

    # ==========================================
    # Anti-Spam / Cooldown Methods
    # ==========================================
    async def can_reply(self, chat_id: str, cooldown_minutes: int = 15) -> bool:
        """Returns True if cooldown expired, False if user replied recently"""
        now = int(time.time())
        limit = now - (cooldown_minutes * 60)
        
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT last_replied FROM cooldowns WHERE chat_id = $1", chat_id)
                if not row:
                    return True
                return row['last_replied'] < limit
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cursor = await db.execute("SELECT last_replied FROM cooldowns WHERE chat_id = ?", (chat_id,))
                row = await cursor.fetchone()
                if not row:
                    return True
                return row[0] < limit

    async def update_cooldown(self, chat_id: str):
        now = int(time.time())
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO cooldowns (chat_id, last_replied) VALUES ($1, $2)
                    ON CONFLICT (chat_id) DO UPDATE SET last_replied = $2
                """, chat_id, now)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("""
                    INSERT INTO cooldowns (chat_id, last_replied) VALUES (?, ?)
                    ON CONFLICT (chat_id) DO UPDATE SET last_replied = ?
                """, (chat_id, now, now))
                await db.commit()

    # ==========================================
    # Chat History (For AI Context)
    # ==========================================
    async def add_chat_history(self, chat_id: str, role: str, text: str):
        now = int(time.time())
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO chat_history (chat_id, role, text, created_at) VALUES ($1, $2, $3, $4)",
                    chat_id, role, text, now
                )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "INSERT INTO chat_history (chat_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                    (chat_id, role, text, now)
                )
                await db.commit()

    async def get_recent_history(self, chat_id: str, limit: int = 5) -> List[Dict[str, str]]:
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT role, text FROM chat_history 
                    WHERE chat_id = $1 
                    ORDER BY created_at DESC LIMIT $2
                """, chat_id, limit)
                # Reverse to get chronological order
                return [{"role": r["role"], "text": r["text"]} for r in reversed(rows)]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cursor = await db.execute("""
                    SELECT role, text FROM chat_history 
                    WHERE chat_id = ? 
                    ORDER BY created_at DESC LIMIT ?
                """, (chat_id, limit))
                rows = await cursor.fetchall()
                return [{"role": r[0], "text": r[1]} for r in reversed(rows)]

    # ==========================================
    # Scheduled Messages
    # ==========================================
    async def add_schedule(self, chat_id: str, message: str, send_at: int) -> int:
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO scheduled_messages (chat_id, message, send_at, status) 
                    VALUES ($1, $2, $3, 'pending') RETURNING id
                """, chat_id, message, send_at)
                return row['id']
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cursor = await db.execute("""
                    INSERT INTO scheduled_messages (chat_id, message, send_at, status) 
                    VALUES (?, ?, ?, 'pending')
                """, (chat_id, message, send_at))
                await db.commit()
                return cursor.lastrowid

    async def get_due_schedules(self) -> List[Dict[str, Any]]:
        now = int(time.time())
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, chat_id, message, send_at FROM scheduled_messages 
                    WHERE status = 'pending' AND send_at <= $1
                """, now)
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cursor = await db.execute("""
                    SELECT id, chat_id, message, send_at FROM scheduled_messages 
                    WHERE status = 'pending' AND send_at <= ?
                """, (now,))
                rows = await cursor.fetchall()
                return [{"id": r[0], "chat_id": r[1], "message": r[2], "send_at": r[3]} for r in rows]

    async def mark_schedule_done(self, schedule_id: int, status: str = 'sent'):
        if self.is_postgres:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("UPDATE scheduled_messages SET status = $1 WHERE id = $2", status, schedule_id)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE scheduled_messages SET status = ? WHERE id = ?", (status, schedule_id))
                await db.commit()

db = Database()
