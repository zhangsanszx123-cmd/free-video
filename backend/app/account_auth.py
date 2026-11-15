"""Password hashing, login sessions, origin checks and rate limits for site accounts."""
import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import urlparse

from fastapi import Request, Response

from . import account_store as store
from . import config
from .errors import AccountError

COOKIE = "freevideo_auth"
USERNAME_RE = re.compile(r"[A-Za-z0-9_]{4,32}")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
TOUCH_INTERVAL = timedelta(minutes=5)
_lock = threading.Lock()
_hits: dict[str, list[float]] = {}
_failures: dict[str, list[float]] = {}


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


# Used for unknown usernames so that response time does not reveal whether an account exists.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def normalize_username(username: str) -> str:
    if not USERNAME_RE.fullmatch(username or ""):
        raise AccountError("INVALID_USERNAME", "用户名需为 4–32 位字母、数字或下划线", 422)
    return username.lower()


def validate_password(password: str, username: str = ""):
    if not 8 <= len(password) <= 128:
        raise AccountError("INVALID_PASSWORD", "密码长度需为 8–128 个字符", 422)
    if not password.strip():
        raise AccountError("INVALID_PASSWORD", "密码不能全部为空白字符", 422)
    if username and password.lower() == username.lower():
        raise AccountError("INVALID_PASSWORD", "密码不能与登录邮箱相同", 422)


def normalize_nickname(nickname: str) -> str:
    nickname = (nickname or "").strip()
    if not 1 <= len(nickname) <= 30:
        raise AccountError("INVALID_NICKNAME", "昵称长度需为 1–30 个字符", 422)
    if any(ord(c) < 32 or ord(c) == 127 for c in nickname):
        raise AccountError("INVALID_NICKNAME", "昵称不能包含控制字符", 422)
    return nickname


def check_origin(request: Request):
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise AccountError("INVALID_ORIGIN", "请从本站页面进行账号操作", 403)
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        same_host = parsed.scheme in ("http", "https") and parsed.netloc == request.headers.get("host")
        if origin.rstrip("/") not in config.ALLOWED_ORIGINS and not same_host:
            raise AccountError("INVALID_ORIGIN", "请求来源不受信任", 403)


def peer(request: Request) -> str:
    # Never trust X-Forwarded-For; see transcription_auth.rate_limit.
    return request.client.host if request.client else "unknown"


def _prune(bucket: dict[str, list[float]], key: str, window: float, now: float) -> list[float]:
    hits = [t for t in bucket.get(key, []) if now - t < window]
    if hits:
        bucket[key] = hits
    else:
        bucket.pop(key, None)
    return hits


def rate_limit(key: str, limit: int, window: float, message: str = "操作过于频繁，请稍后再试"):
    now = time.monotonic()
    with _lock:
        if len(_prune(_hits, key, window, now)) >= limit:
            raise AccountError("RATE_LIMIT", message, 429)
        _hits.setdefault(key, []).append(now)


LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW = 5, 900


def login_blocked(username_key: str) -> bool:
    with _lock:
        return len(_prune(_failures, username_key, LOGIN_FAILURE_WINDOW, time.monotonic())) >= LOGIN_FAILURE_LIMIT


def record_login_failure(username_key: str):
    with _lock:
        _failures.setdefault(username_key, []).append(time.monotonic())


def clear_login_failures(username_key: str):
    with _lock:
        _failures.pop(username_key, None)


def reset_limits():
    with _lock:
        _hits.clear()
        _failures.clear()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_session(request: Request) -> tuple[str, dict]:
    token = secrets.token_urlsafe(32)
    now = store.utcnow()
    return token, {"id": secrets.token_hex(16), "token_hash": token_hash(token), "created_at": now,
                   "expires_at": now + timedelta(days=config.AUTH_SESSION_DAYS),
                   "user_agent": (request.headers.get("user-agent") or "")[:255], "ip": peer(request)[:45]}


def set_cookie(response: Response, token: str):
    response.set_cookie(COOKIE, token, max_age=config.AUTH_SESSION_DAYS * 86400, httponly=True,
                        secure=config.SESSION_SECURE, samesite="lax", path="/api")


def clear_cookie(response: Response):
    response.delete_cookie(COOKIE, path="/api", httponly=True, secure=config.SESSION_SECURE, samesite="lax")


def _token(request: Request) -> str | None:
    token = request.cookies.get(COOKIE, "")
    return token if 20 <= len(token) <= 100 and token.isascii() else None


def current_user(request: Request) -> dict | None:
    """Return the logged-in user (with session_id) or None. Database failures raise 503."""
    token = _token(request)
    if not token:
        return None
    row = store.session_user(token_hash(token))
    if not row:
        return None
    if store.utcnow() - row["last_seen_at"] >= TOUCH_INTERVAL:
        store.touch_session(row["session_id"])
    return row


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise AccountError("AUTH_REQUIRED", "请先登录后使用该功能", 401)
    request.state.account_user = user
    return user


def revoke_current(request: Request):
    token = _token(request)
    if token:
        store.delete_session_by_token(token_hash(token))


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not email.isascii() or email.count('@') != 1:
        raise AccountError("INVALID_EMAIL", "请输入正确的邮箱地址", 422)
    local, domain = email.split('@')
    labels = domain.split('.')
    if (not 1 <= len(local) <= 64 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+", local)
            or local.startswith('.') or local.endswith('.') or '..' in local
            or len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
            or not re.fullmatch(r"[a-z]{2,63}", labels[-1])):
        raise AccountError("INVALID_EMAIL", "请输入正确的邮箱地址", 422)
    return email
