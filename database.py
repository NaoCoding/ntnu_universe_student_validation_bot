"""Small SQLite store for pending email and manual-verification sessions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EmailSession:
    user_id: int
    guild_id: int
    email: str
    student_number: str
    code: str
    expires_at: float


@dataclass(frozen=True)
class ManualSession:
    user_id: int
    guild_id: int


class VerificationDatabase:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_sessions (
                user_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                student_number TEXT NOT NULL,
                code TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_sessions (
                user_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                created_at REAL NOT NULL DEFAULT (unixepoch())
            )
            """
        )
        self.connection.commit()

    def save_email_session(
        self,
        user_id: int,
        guild_id: int,
        email: str,
        student_number: str,
        code: str,
        expires_at: float,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO email_sessions (user_id, guild_id, email, student_number, code, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              guild_id=excluded.guild_id,
              email=excluded.email,
              student_number=excluded.student_number,
              code=excluded.code,
              expires_at=excluded.expires_at
            """,
            (user_id, guild_id, email, student_number, code, expires_at),
        )
        self.connection.commit()

    def get_email_session(self, user_id: int) -> EmailSession | None:
        row = self.connection.execute(
            "SELECT * FROM email_sessions WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        return EmailSession(**dict(row))

    def delete_email_session(self, user_id: int) -> None:
        self.connection.execute("DELETE FROM email_sessions WHERE user_id = ?", (user_id,))
        self.connection.commit()

    def save_manual_session(self, user_id: int, guild_id: int) -> None:
        self.connection.execute(
            """
            INSERT INTO manual_sessions (user_id, guild_id) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET guild_id=excluded.guild_id, created_at=unixepoch()
            """,
            (user_id, guild_id),
        )
        self.connection.commit()

    def get_manual_session(self, user_id: int) -> ManualSession | None:
        row = self.connection.execute(
            "SELECT user_id, guild_id FROM manual_sessions WHERE user_id = ?", (user_id,)
        ).fetchone()
        return ManualSession(**dict(row)) if row else None

