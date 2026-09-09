import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .audit import emit
from .common import ApiError, utc

HASHER = PasswordHasher()
# The dummy hash equalizes unknown-user and incorrect-password verification work.
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


def token_key(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    def origin(self, headers):
        if headers.get("origin") not in self.settings.allowed_origins:
            raise ApiError("FORBIDDEN", "Недопустимый источник запроса.", 403)

    def login(self, body, request_id, address):
        now = self.settings.clock()
        error = None
        with self.store.transaction() as tx:
            bucket = token_key(address)
            attempts = [t for t in tx.get("login_rate", bucket, []) if now - t < 60]
            if len(attempts) >= 10:
                raise ApiError("RATE_LIMITED", "Слишком много попыток входа.", 429, retryable=True)
            tx.put("login_rate", bucket, attempts + [now])
            user = next((u for u in tx.list("user") if u["actor"]["login"] == body["login"]), None)
            try:
                verified = HASHER.verify(user["password_hash"] if user else DUMMY_HASH, body["password"])
            except (VerificationError, InvalidHashError):
                verified = False
            if not verified or not user or user["blocked"]:
                emit(tx, None, "LOGIN_FAILED", request_id, now=now, result="FAILED")
                error = ApiError("LOGIN_FAILED", "Неверный логин или пароль.", 401)
            else:
                token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
                session = {"user_id": user["actor"]["user_id"], "csrf": csrf, "created": now, "touched": now}
                tx.put("session", token_key(token), session)
                emit(tx, user["actor"], "LOGIN_SUCCEEDED", request_id, now=now)
                result = self.dto(session, user["actor"])
        if error:
            raise error
        return result, token

    def dto(self, session, actor):
        end = min(
            session["created"] + self.settings.absolute_session_seconds,
            session["touched"] + self.settings.idle_session_seconds,
        )
        return {"actor": actor, "expires_at": utc(end), "csrf_token": session["csrf"]}

    def authenticate(self, token):
        now = self.settings.clock()
        with self.store.transaction() as tx:
            session = tx.get("session", token_key(token or ""))
            user = tx.get("user", session["user_id"]) if session else None
            if (
                not session
                or not user
                or user["blocked"]
                or now
                >= min(
                    session["created"] + self.settings.absolute_session_seconds,
                    session["touched"] + self.settings.idle_session_seconds,
                )
            ):
                raise ApiError("UNAUTHENTICATED", "Требуется вход в систему.", 401)
            return session, user["actor"]

    def touch(self, token):
        with self.store.transaction() as tx:
            session = tx.get("session", token_key(token))
            if session:
                session["touched"] = self.settings.clock()
                tx.put("session", token_key(token), session)

    def csrf(self, headers, session):
        self.origin(headers)
        if not hmac.compare_digest(headers.get("x-csrf-token", ""), session["csrf"]):
            raise ApiError("CSRF_FAILED", "Недействительный CSRF-токен.", 403)

    def logout(self, token, actor, request_id):
        with self.store.transaction() as tx:
            tx.delete("session", token_key(token))
            emit(tx, actor, "LOGOUT", request_id, now=self.settings.clock())
