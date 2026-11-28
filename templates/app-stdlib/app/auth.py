"""Accounts, password hashing and sessions. Python standard library only.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes (16-byte random salt, the
iteration count stored per account). Session tokens are random and only their
SHA-256 is stored; each session has its own CSRF token. No default account exists:
the first administrator is created with `python3 manage.py create-account`.

Sign-in does the same PBKDF2 work whether or not the e-mail has an account (a dummy
hash with the schema's iteration count), so response time does not reveal which
accounts exist. Failed sign-ins are counted in sliding windows of LOCKOUT_SECONDS
(15 minutes) under three limits, all checked before any account lookup or hashing:

- one e-mail from one client address: LOCKOUT_FAILURES (5) failures in any 15 minutes,
  the "rate limit on sign-in (5 failures per 15 minutes)";
- one client address, any e-mails: ADDRESS_FAILURES, so rotating e-mails (each of
  which costs a full PBKDF2) cannot make one client burn unbounded CPU;
- one e-mail from all client addresses together: ACCOUNT_FAILURES, a ceiling on
  guessing one account from many addresses.

While a window holds its limit, sign-in for it is refused (429 with Retry-After, the
password is not checked) until the oldest failure counted in it is LOCKOUT_SECONDS old:
that wait is the backoff, so no window ever admits more than its limit. An attempt is
counted when it is admitted (so parallel requests cannot pass a limit) and stops
counting once its password proves correct; a correct password also clears its (e-mail,
address) pair. E-mails are counted whether or not an account has them. Failures from
one address never refuse the pair of another address. ACCOUNT_FAILURES failures from
several addresses together hold one e-mail at every address except those that signed in
to it successfully within KNOWN_SECONDS (those keep their own pair and address limits),
so a distributed guesser cannot keep the owner out of their usual address. The counters
are in process memory, bounded to MAX_TRACKED keys each, and reset when the server
restarts.
"""
import datetime
import hashlib
import hmac
import math
import secrets
import threading
import time

from . import db

MIN_PASSWORD = 12
MAX_PASSWORD = 256
MAX_EMAIL = 254
LOCKOUT_SECONDS = 900  # the sliding window of every sign-in limit
LOCKOUT_FAILURES = 5  # per (e-mail, client address)
ADDRESS_FAILURES = 20  # per client address, any e-mails
ACCOUNT_FAILURES = 20  # per e-mail, all client addresses together
KNOWN_SECONDS = 30 * 24 * 3600  # an address that signed in to an e-mail is exempt from its ceiling this long
MAX_TRACKED = 10000  # keys kept per counter


class AuthError(Exception):
    def __init__(self, status, code, message, retry_after=None):
        super().__init__(message)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


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
    """Login, logout and session lookup with the sign-in failure limits described above."""

    def __init__(self, schema):
        self.schema = schema
        self.hours = schema.auth.get("session_hours", 12)
        self._failures = {"pair": {}, "address": {}, "account": {}}
        self._known = {}  # (e-mail, address) -> time of its latest successful sign-in
        self._lock = threading.Lock()
        self.clock = time.monotonic
        # a salt and a digest no password produces: verifying against them costs the full PBKDF2 work
        self._dummy = (secrets.token_bytes(16).hex(), secrets.token_bytes(32).hex())

    @staticmethod
    def _keys(email, source):
        who, address = email.strip().casefold(), str(source or "")
        return {"pair": (who, address), "address": address, "account": who}

    def _recent(self, kind, key, now):
        table = self._failures[kind]
        recent = [t for t in table.get(key, ()) if t > now - LOCKOUT_SECONDS]
        if recent:
            table[key] = recent
        else:
            table.pop(key, None)
        return recent

    @staticmethod
    def _wait(recent, limit, now):
        """Seconds a window with these failures still refuses sign-in (0: it admits one)."""
        if len(recent) < limit:
            return 0
        return recent[-limit] + LOCKOUT_SECONDS - now

    def _admit(self, keys):
        """Count one attempt in every window, or none when a window is full.

        Returns (None, stamp) when admitted, else (seconds until every window admits, None)."""
        limits = {"pair": LOCKOUT_FAILURES, "address": ADDRESS_FAILURES, "account": ACCOUNT_FAILURES}
        with self._lock:
            now = self.clock()
            known = self._known.get(keys["pair"])
            if known is not None and known <= now - KNOWN_SECONDS:
                del self._known[keys["pair"]]
                known = None
            wait = max(self._wait(self._recent(kind, key, now), limits[kind], now) for kind, key in keys.items()
                       if not (kind == "account" and known is not None))
            if wait > 0:
                return wait, None
            for kind, key in keys.items():
                table = self._failures[kind]
                if key not in table and len(table) >= MAX_TRACKED:
                    for other in list(table):
                        self._recent(kind, other, now)
                    while len(table) >= MAX_TRACKED:
                        del table[min(table, key=lambda k: table[k][-1])]
                table.setdefault(key, []).append(now)
            return None, now

    def _succeeded(self, keys, stamp):
        """The password was right: the admitted attempt is no failure, the pair starts again and
        its address is known for this e-mail."""
        with self._lock:
            self._failures["pair"].pop(keys["pair"], None)
            if keys["pair"] not in self._known and len(self._known) >= MAX_TRACKED:
                del self._known[min(self._known, key=self._known.get)]
            self._known[keys["pair"]] = self.clock()
            for kind in ("address", "account"):
                entries = self._failures[kind].get(keys[kind])
                if entries and stamp in entries:
                    entries.remove(stamp)
                    if not entries:
                        del self._failures[kind][keys[kind]]

    def login(self, connection, email, password, source=None):
        if (not isinstance(email, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD
                or len(email) > MAX_EMAIL):
            raise AuthError(400, "validation_failed", "email and password are required")
        keys = self._keys(email, source)
        wait, stamp = self._admit(keys)
        if wait is not None:
            raise AuthError(429, "too_many_attempts", "too many failed sign-in attempts; try again later",
                            retry_after=max(1, math.ceil(wait)))
        row = db.account_by_email(connection, email.strip())
        if row is None:
            verify_password(password, *self._dummy, self.schema.auth["pbkdf2_iterations"])  # same work, no account
        if row is None or not verify_password(password, row["password_salt"], row["password_hash"],
                                              row["password_iterations"]):
            raise AuthError(401, "invalid_credentials", "e-mail or password is not correct")  # stays counted
        self._succeeded(keys, stamp)
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
