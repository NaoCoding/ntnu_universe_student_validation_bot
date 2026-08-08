"""Validation and parsing helpers for NTNU student email addresses."""

from __future__ import annotations

import re


# XXX47XXXs@... where every X is a digit and the final s is case-insensitive.
STUDENT_EMAIL_PATTERN = re.compile(
    r"^(?P<student_number>\d{3}47\d{3})(?P<suffix>[sS])@"
    r"(?P<domain>gapps\.ntnu\.edu\.tw|ntnu\.edu\.tw)$",
    re.IGNORECASE,
)


def parse_student_email(value: str) -> tuple[str, str] | None:
    """Return (normalized student number, normalized email), or None."""

    normalized = value.strip().lower()
    match = STUDENT_EMAIL_PATTERN.fullmatch(normalized)
    if not match:
        return None
    return match.group("student_number"), normalized

