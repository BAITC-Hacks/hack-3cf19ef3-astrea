"""Invitation-only user registration and password authentication."""

import hashlib
import hmac
import os
import re
import secrets
from typing import Optional

from app.db import database_url


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegistrationError(ValueError):
    """A safe, user-facing registration error."""


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a fresh random salt."""

    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return (
        f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    """Verify a password without leaking timing information."""

    try:
        algorithm, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _normalized_email(email: str) -> str:
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise RegistrationError("Введите корректный email")
    return normalized


def _validate_registration(
    email: str,
    full_name: str,
    password: str,
    invite_code: str,
) -> tuple[str, str]:
    expected_code = os.getenv("INVITE_CODE", "")
    if not expected_code:
        raise RegistrationError("Регистрация закрыта")
    if not hmac.compare_digest(invite_code, expected_code):
        raise RegistrationError("Неверный код приглашения")
    normalized_email = _normalized_email(email)
    normalized_name = full_name.strip()
    if not normalized_name:
        raise RegistrationError("Укажите имя")
    if len(password) < 8:
        raise RegistrationError("Пароль должен содержать не менее 8 символов")
    return normalized_email, normalized_name


def _connection_url(value: Optional[str]) -> str:
    resolved = value or database_url()
    if not resolved:
        raise RuntimeError("DATABASE_URL не задан")
    return resolved


def _driver() -> tuple[object, object]:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg, dict_row


def register(
    email: str,
    full_name: str,
    password: str,
    invite_code: str,
    connection_url: Optional[str] = None,
) -> dict[str, object]:
    """Create a user after validating the invitation and credentials."""

    normalized_email, normalized_name = _validate_registration(
        email, full_name, password, invite_code
    )
    psycopg, dict_row = _driver()
    try:
        with psycopg.connect(
            _connection_url(connection_url), row_factory=dict_row
        ) as connection:
            user = connection.execute(
                """
                INSERT INTO users (email, full_name, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id, email, full_name
                """,
                (normalized_email, normalized_name, hash_password(password)),
            ).fetchone()
    except psycopg.errors.UniqueViolation as error:
        raise RegistrationError("Такой email уже есть") from error
    return dict(user)


def authenticate(
    email: str,
    password: str,
    connection_url: Optional[str] = None,
) -> Optional[dict[str, object]]:
    """Return the authenticated user and update their last login timestamp."""

    try:
        normalized_email = _normalized_email(email)
    except RegistrationError:
        return None
    psycopg, dict_row = _driver()
    with psycopg.connect(
        _connection_url(connection_url), row_factory=dict_row
    ) as connection:
        user = connection.execute(
            """
            SELECT id, email, full_name, password_hash
            FROM users
            WHERE email = %s
            """,
            (normalized_email,),
        ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            return None
        connection.execute(
            "UPDATE users SET last_login_at = now() WHERE id = %s",
            (user["id"],),
        )
    return {key: user[key] for key in ("id", "email", "full_name")}


__all__ = [
    "RegistrationError",
    "authenticate",
    "hash_password",
    "register",
    "verify_password",
]
