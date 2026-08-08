"""Verification-code generation and constant-time comparison helpers."""

from __future__ import annotations

import hashlib
import hmac


def make_verification_code(
    prefix: str, secret_part_1: str, secret_part_2: str
) -> str:
    """Generate the configured MD5 code.

    This implements MD5(CONCAT(prefix, CONCAT(part_1, part_2))) exactly.
    The values are supplied by environment variables and are never hard-coded.
    """

    source = f"{prefix}{secret_part_1}{secret_part_2}"
    return hashlib.md5(source.encode("utf-8")).hexdigest()


def codes_match(expected: str, submitted: str) -> bool:
    return hmac.compare_digest(expected.lower(), submitted.strip().lower())

