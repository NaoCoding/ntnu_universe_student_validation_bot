"""SQLite store for pending sessions and verification audit records."""

from __future__ import annotations

import sqlite3
import time
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
    requested_at: float


@dataclass(frozen=True)
class ManualSession:
    user_id: int
    guild_id: int
    requested_at: float


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
                expires_at REAL NOT NULL,
                requested_at REAL NOT NULL DEFAULT 0
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
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                email TEXT,
                student_number TEXT,
                requested_at REAL NOT NULL,
                passed_at REAL
            )
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_verification_email_requests
            ON verification_records (method, email, requested_at)
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_verification_student_passes
            ON verification_records (method, student_number, passed_at)
            """
        )
        email_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(email_sessions)")
        }
        if "requested_at" not in email_columns:
            self.connection.execute(
                "ALTER TABLE email_sessions ADD COLUMN requested_at REAL NOT NULL DEFAULT 0"
            )
        self.connection.execute(
            """
            INSERT INTO verification_records
                (user_id, guild_id, method, email, student_number, requested_at)
            SELECT e.user_id, e.guild_id, 'email', e.email, e.student_number,
                   COALESCE(NULLIF(e.requested_at, 0), e.expires_at)
            FROM email_sessions AS e
            WHERE NOT EXISTS (
                SELECT 1 FROM verification_records AS r
                WHERE r.user_id = e.user_id AND r.method = 'email'
                  AND r.requested_at = COALESCE(NULLIF(e.requested_at, 0), e.expires_at)
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO verification_records
                (user_id, guild_id, method, requested_at)
            SELECT m.user_id, m.guild_id, 'manual', m.created_at
            FROM manual_sessions AS m
            WHERE NOT EXISTS (
                SELECT 1 FROM verification_records AS r
                WHERE r.user_id = m.user_id AND r.method = 'manual'
                  AND r.requested_at = m.created_at
            )
            """
        )
        self.connection.commit()

    def _record_request(
        self,
        user_id: int,
        guild_id: int,
        method: str,
        requested_at: float,
        email: str | None = None,
        student_number: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO verification_records
                (user_id, guild_id, method, email, student_number, requested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, guild_id, method, email, student_number, requested_at),
        )

    def save_email_session(
        self,
        user_id: int,
        guild_id: int,
        email: str,
        student_number: str,
        code: str,
        expires_at: float,
        requested_at: float | None = None,
    ) -> None:
        requested_at = requested_at if requested_at is not None else time.time()
        self.connection.execute(
            """
            INSERT INTO email_sessions
                (user_id, guild_id, email, student_number, code, expires_at, requested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              guild_id=excluded.guild_id,
              email=excluded.email,
              student_number=excluded.student_number,
              code=excluded.code,
              expires_at=excluded.expires_at,
              requested_at=excluded.requested_at
            """,
            (user_id, guild_id, email, student_number, code, expires_at, requested_at),
        )
        self._record_request(user_id, guild_id, "email", requested_at, email, student_number)
        self.connection.commit()

    def get_email_session(self, user_id: int) -> EmailSession | None:
        row = self.connection.execute(
            "SELECT user_id, guild_id, email, student_number, code, expires_at, "
            "COALESCE(requested_at, expires_at) AS requested_at "
            "FROM email_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return EmailSession(**dict(row))

    def delete_email_session(self, user_id: int) -> None:
        self.connection.execute("DELETE FROM email_sessions WHERE user_id = ?", (user_id,))
        self.connection.commit()

    def is_email_send_rate_limited(
        self, email: str, now: float | None = None, window_seconds: int = 60
    ) -> bool:
        """Return whether this email address was used for a recent request."""

        now = now if now is not None else time.time()
        row = self.connection.execute(
            """
            SELECT 1 FROM verification_records
            WHERE method = 'email' AND email = ? AND requested_at > ?
            LIMIT 1
            """,
            (email, now - window_seconds),
        ).fetchone()
        return row is not None

    def has_recent_passed_student_verification(
        self,
        student_number: str,
        now: float | None = None,
        cooldown_seconds: int = 30 * 24 * 60 * 60,
    ) -> bool:
        """Return whether a student number passed automated verification recently."""

        now = now if now is not None else time.time()
        row = self.connection.execute(
            """
            SELECT 1 FROM verification_records
            WHERE method = 'email'
              AND student_number = ?
              AND passed_at IS NOT NULL
              AND passed_at > ?
            LIMIT 1
            """,
            (student_number, now - cooldown_seconds),
        ).fetchone()
        return row is not None

    def save_manual_session(
        self, user_id: int, guild_id: int, requested_at: float | None = None
    ) -> None:
        requested_at = requested_at if requested_at is not None else time.time()
        self.connection.execute(
            """
            INSERT INTO manual_sessions (user_id, guild_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                guild_id=excluded.guild_id,
                created_at=excluded.created_at
            """,
            (user_id, guild_id, requested_at),
        )
        self._record_request(user_id, guild_id, "manual", requested_at)
        self.connection.commit()

    def get_manual_session(self, user_id: int) -> ManualSession | None:
        row = self.connection.execute(
            "SELECT user_id, guild_id, created_at AS requested_at "
            "FROM manual_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return ManualSession(**dict(row)) if row else None

    def mark_verification_passed(
        self, user_id: int, method: str, passed_at: float | None = None
    ) -> float:
        """Mark the user's latest request for this method as passed."""

        passed_at = passed_at if passed_at is not None else time.time()
        row = self.connection.execute(
            """
            SELECT id FROM verification_records
            WHERE user_id = ? AND method = ? AND passed_at IS NULL
            ORDER BY requested_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, method),
        ).fetchone()
        if row is None:
            raise LookupError(f"No pending {method} verification for user {user_id}")
        self.connection.execute(
            "UPDATE verification_records SET passed_at = ? WHERE id = ?",
            (passed_at, row["id"]),
        )
        self.connection.commit()
        return passed_at
