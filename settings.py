"""Environment-backed application settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _channel_id(name: str) -> int:
    value = _required(name)
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a Discord channel ID") from exc


def _role_map(environment_name: str) -> dict[str, str]:
    raw = os.getenv(environment_name, "{}").strip() or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{environment_name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{environment_name} must be a JSON object")
    return {str(key).strip(): str(role).strip() for key, role in value.items()}


@dataclass(frozen=True)
class Settings:
    discord_token: str
    verification_channel_id: int
    admin_channel_id: int
    gmail_credentials_file: Path
    gmail_token_file: Path
    gmail_sender_email: str
    hash_secret_part_1: str
    hash_secret_part_2: str
    student_role_map: dict[str, str]
    student_role_prefix_map: dict[str, str]
    default_student_role: str | None
    verification_code_ttl_minutes: int
    email_send_rate_limit_seconds: int
    student_reverification_cooldown_days: int
    database_file: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        try:
            ttl = int(os.getenv("VERIFICATION_CODE_TTL_MINUTES", "10"))
        except ValueError as exc:
            raise RuntimeError("VERIFICATION_CODE_TTL_MINUTES must be an integer") from exc
        if ttl <= 0:
            raise RuntimeError("VERIFICATION_CODE_TTL_MINUTES must be positive")

        try:
            email_rate_limit = int(os.getenv("EMAIL_SEND_RATE_LIMIT_SECONDS", "60"))
        except ValueError as exc:
            raise RuntimeError("EMAIL_SEND_RATE_LIMIT_SECONDS must be an integer") from exc
        if email_rate_limit <= 0:
            raise RuntimeError("EMAIL_SEND_RATE_LIMIT_SECONDS must be positive")

        try:
            reverification_days = int(
                os.getenv("STUDENT_REVERIFICATION_COOLDOWN_DAYS", "30")
            )
        except ValueError as exc:
            raise RuntimeError(
                "STUDENT_REVERIFICATION_COOLDOWN_DAYS must be an integer"
            ) from exc
        if reverification_days <= 0:
            raise RuntimeError("STUDENT_REVERIFICATION_COOLDOWN_DAYS must be positive")

        default_role = os.getenv("DEFAULT_STUDENT_ROLE", "").strip() or None
        return cls(
            discord_token=_required("DISCORD_TOKEN"),
            verification_channel_id=_channel_id("VERIFICATION_CHANNEL_ID"),
            admin_channel_id=_channel_id("ADMIN_CHANNEL_ID"),
            gmail_credentials_file=Path(os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")),
            gmail_token_file=Path(os.getenv("GMAIL_TOKEN_FILE", "token.json")),
            gmail_sender_email=_required("GMAIL_SENDER_EMAIL"),
            hash_secret_part_1=_required("VERIFICATION_HASH_SECRET_PART_1"),
            hash_secret_part_2=_required("VERIFICATION_HASH_SECRET_PART_2"),
            student_role_map=_role_map("STUDENT_ROLE_MAP_JSON"),
            student_role_prefix_map=_role_map("STUDENT_ROLE_PREFIX_MAP_JSON"),
            default_student_role=default_role,
            verification_code_ttl_minutes=ttl,
            email_send_rate_limit_seconds=email_rate_limit,
            student_reverification_cooldown_days=reverification_days,
            database_file=Path(os.getenv("DATABASE_FILE", "verification.db")),
        )
