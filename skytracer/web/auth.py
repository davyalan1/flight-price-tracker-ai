"""Password hashing, signed session cookies, and login rate limiting.

Password storage: PBKDF2-HMAC-SHA256 (stdlib hashlib, no extra dependency),
stored as `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>` under the
`web.admin_password` settings key — the same key config.example.toml ships
as an empty string, which is what triggers the first-run "create a
password" flow.

Session cookies: itsdangerous signs a timestamped token so the server never
needs to keep session state; a session is just "cookie verifies and isn't
older than SESSION_MAX_AGE_SECONDS".
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request

from skytracer import settings_store

PBKDF2_ITERATIONS = 200_000
SESSION_COOKIE_NAME = "skytracer_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 days
SESSION_SECRET_KEY = "internal.web_session_secret"

MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300

# In-memory only: fine for a single-user, single-process homelab app. Resets
# on restart, which just means a fresh rate-limit window — not a security
# regression for this threat model.
_failed_logins: dict[str, list[float]] = {}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations_str, salt, expected_digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), int(iterations_str)
    ).hex()
    return hmac.compare_digest(candidate, expected_digest)


def get_or_create_session_secret(conn: sqlite3.Connection) -> str:
    secret = settings_store.get(conn, SESSION_SECRET_KEY, "")
    if secret:
        return secret
    secret = secrets.token_hex(32)
    settings_store.set(conn, SESSION_SECRET_KEY, secret)
    return secret


def rotate_session_secret(conn: sqlite3.Connection) -> str:
    """Invalidate every existing session cookie (e.g. on password change) by
    replacing the secret they were signed with. Returns the new secret so
    the caller can immediately issue a fresh cookie for the current user.
    """
    secret = secrets.token_hex(32)
    settings_store.set(conn, SESSION_SECRET_KEY, secret)
    return secret


def create_session_cookie(conn: sqlite3.Connection) -> str:
    serializer = URLSafeTimedSerializer(get_or_create_session_secret(conn))
    return serializer.dumps({"authenticated": True})


def is_valid_session_cookie(conn: sqlite3.Connection, token: str | None) -> bool:
    if not token:
        return False
    serializer = URLSafeTimedSerializer(get_or_create_session_secret(conn))
    try:
        serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return True


def is_logged_in(conn: sqlite3.Connection, request: Request) -> bool:
    return is_valid_session_cookie(conn, request.cookies.get(SESSION_COOKIE_NAME))


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_rate_limited(key: str) -> bool:
    cutoff = time.time() - LOGIN_LOCKOUT_SECONDS
    attempts = [t for t in _failed_logins.get(key, []) if t >= cutoff]
    _failed_logins[key] = attempts
    return len(attempts) >= MAX_LOGIN_ATTEMPTS


def record_failed_login(key: str) -> None:
    _failed_logins.setdefault(key, []).append(time.time())


def clear_failed_logins(key: str) -> None:
    _failed_logins.pop(key, None)
