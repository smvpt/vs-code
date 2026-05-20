import sqlite3
from typing import Optional
from config import DEFAULT_TIMEZONE, DB_PATH


class Database:
    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()

    # Добавь это в database.py в класс Database
    def save_user_query(self, user_id, username, text):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO support_userquery (user_id, username, question, is_answered, created_at) VALUES (?, ?, ?, 0, datetime('now'))",
                (user_id, username, text)
            )
            
    def log_query(self, user_id: int, text: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO support_userquery (user_id, question, is_answered, created_at) VALUES (?, ?, 0, datetime('now'))",
                (user_id, text)
            )

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id   INTEGER PRIMARY KEY,
                    name      TEXT,
                    timezone  TEXT DEFAULT 'Europe/Moscow',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    text       TEXT NOT NULL,
                    datetime   TEXT NOT NULL,
                    is_sent    INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
            """)

    # ── Users ──────────────────────────────────────────────────────────────
    def add_user(self, user_id: int, name: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, name, timezone) VALUES (?, ?, ?)",
                (user_id, name, DEFAULT_TIMEZONE),
            )

    def get_timezone(self, user_id: int) -> str:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT timezone FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["timezone"] if row else DEFAULT_TIMEZONE

    def set_timezone(self, user_id: int, timezone: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET timezone = ? WHERE user_id = ?",
                (timezone, user_id),
            )

    # ── Reminders ──────────────────────────────────────────────────────────
    def add_reminder(self, user_id: int, text: str, dt_iso: str) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (user_id, text, datetime) VALUES (?, ?, ?)",
                (user_id, text, dt_iso),
            )
        return cur.lastrowid

    def get_reminders(self, user_id: int) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, text, datetime FROM reminders "
                "WHERE user_id = ? AND is_sent = 0 ORDER BY datetime",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_pending(self) -> list[dict]:
        """Все неотправленные напоминания (для восстановления после перезапуска)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, user_id, text, datetime FROM reminders WHERE is_sent = 0"
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, reminder_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE reminders SET is_sent = 1 WHERE id = ?", (reminder_id,)
            )

    def delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, user_id),
            )
        return cur.rowcount > 0
