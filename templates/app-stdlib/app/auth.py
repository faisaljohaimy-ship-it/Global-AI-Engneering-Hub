"""Accounts, password hashing and sessions. Python standard library only.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes (16-byte random salt, the
iteration count stored per account). Session tokens are random and only their
SHA-256 is stored; each session has its own CSRF token. No default account exists:
the first administrator is created with `python3 manage.py create-account`.
"""
import datetime
import hashlib
import hmac
import secrets
import threading
import time

from . import db

MIN_PASSWORD = 12
MAX_PASSWORD = 256
LOCKOUT_FAILURES = 5
LOCKOUT_SECONDS = 900


class AuthError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def hash_password(password, iterations, salt=None):
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, digest_hex, iterations):
    _, digest = hash_password(password, iterations, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest, digest_hex)


def check_password(password):
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise AuthError(400, "weak_password", f"password must be {MIN_PASSWORD}-{MAX_PASSWORD} characters")


def utc(moment=None):
    return (moment or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_account(connection, schema, email, role, password, iterations=None):
    from . import model
    if not isinstance(email, str) or not model.EMAIL.fullmatch(email.strip()) or len(email) > 254:
        raise AuthError(400, "invalid_email", "a valid e-mail address is required")
    if role not in schema.auth["roles"]:
        raise AuthError(400, "invalid_role", "unknown role")
    check_password(password)
    if db.account_by_email(connection, email.strip()) is not None:
        raise AuthError(409, "duplicate", "an account with this e-mail already exists")
    iterations = iterations or schema.auth["pbkdf2_iterations"]
    salt, digest = hash_password(password, iterations)
    return db.create_account(connection, email.strip(), role, salt, digest, iterations, utc())


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Sessions:
    """Login, logout and session lookup with a per-address failure lockout."""

    def __init__(self, schema):
        self.schema = schema
        self.hours = schema.auth.get("session_hours", 12)
        self._failures = {}
        self._lock = threading.Lock()

    def _locked(self, key):
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if t > time.monotonic() - LOCKOUT_SECONDS]
            self._failures[key] = recent
            return len(recent) >= LOCKOUT_FAILURES

    def _fail(self, key):
        with self._lock:
            self._failures.setdefault(key, []).append(time.monotonic())

    def login(self, connection, email, password):
        if not isinstance(email, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD:
            raise AuthError(400, "validation_failed", "email and password are required")
        key = email.strip().casefold()
        if self._locked(key):
            raise AuthError(429, "too_many_attempts", "too many failed sign-in attempts; try again later")
        row = db.account_by_email(connection, email.strip())
        if row is None or not verify_password(password, row["password_salt"], row["password_hash"],
                                              row["password_iterations"]):
            self._fail(key)
            raise AuthError(401, "invalid_credentials", "e-mail or password is not correct")
        with self._lock:
            self._failures.pop(key, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = datetime.datetime.now(datetime.timezone.utc)
        db.create_session(connection, token_digest(token), row["id"], csrf, utc(now),
                          utc(now + datetime.timedelta(hours=self.hours)))
        return token, {"id": row["id"], "email": row["email"], "role": row["role"], "csrf_token": csrf}

    def account(self, connection, token):
        if not token or len(token) > 200:
            return None
        return db.session_account(connection, token_digest(token), utc())

    def logout(self, connection, token):
        db.delete_session(connection, token_digest(token))
