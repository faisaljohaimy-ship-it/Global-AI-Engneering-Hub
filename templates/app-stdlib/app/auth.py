"""Accounts, password hashing and sessions. Python standard library only.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes (16-byte random salt, the
iteration count stored per account). Session tokens are random and only their
SHA-256 is stored; each session has its own CSRF token. No default account exists:
the first administrator is created with `python3 manage.py create-account`.

Sign-in does the same PBKDF2 work whether or not the e-mail has an account (a dummy
hash with the schema's iteration count), so response time does not reveal which
accounts exist. Failed sign-ins are counted per (e-mail, client address): after
LOCKOUT_FAILURES failures within LOCKOUT_SECONDS that pair is refused (429) for a
backoff that starts at BACKOFF_SECONDS and doubles with each further failure, up to
LOCKOUT_SECONDS. Keying by the pair means nobody can lock an account out from another
address; the backoff (instead of one long hard lock) keeps a legitimate user's own
mistakes cheap while still slowing guessing. The table is in process memory and bounded.
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
BACKOFF_SECONDS = 30
MAX_TRACKED = 10000


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
    """Login, logout and session lookup with a per-(e-mail, client address) failure backoff."""

    def __init__(self, schema):
        self.schema = schema
        self.hours = schema.auth.get("session_hours", 12)
        self._failures = {}
        self._lock = threading.Lock()
        self.clock = time.monotonic
        # a salt and a digest no password produces: verifying against them costs the full PBKDF2 work
        self._dummy = (secrets.token_bytes(16).hex(), secrets.token_bytes(32).hex())

    def _recent(self, key, now):
        recent = [t for t in self._failures.get(key, []) if t > now - LOCKOUT_SECONDS]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def _locked(self, key):
        with self._lock:
            now = self.clock()
            recent = self._recent(key, now)
            if len(recent) < LOCKOUT_FAILURES:
                return False
            backoff = min(LOCKOUT_SECONDS, BACKOFF_SECONDS * 2 ** (len(recent) - LOCKOUT_FAILURES))
            return now < recent[-1] + backoff

    def _fail(self, key):
        with self._lock:
            now = self.clock()
            if key not in self._failures and len(self._failures) >= MAX_TRACKED:
                for other in list(self._failures):
                    self._recent(other, now)
                while len(self._failures) >= MAX_TRACKED:
                    oldest = min(self._failures, key=lambda k: self._failures[k][-1])
                    del self._failures[oldest]
            self._failures.setdefault(key, []).append(now)

    def login(self, connection, email, password, source=None):
        if not isinstance(email, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD:
            raise AuthError(400, "validation_failed", "email and password are required")
        key = (email.strip().casefold(), str(source or ""))
        if self._locked(key):
            raise AuthError(429, "too_many_attempts", "too many failed sign-in attempts; try again later")
        row = db.account_by_email(connection, email.strip())
        if row is None:
            verify_password(password, *self._dummy, self.schema.auth["pbkdf2_iterations"])  # same work, no account
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
