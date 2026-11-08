"""Signed anonymous sessions; task IDs alone do not authorize reading results."""
import hashlib
import hmac
import re
import secrets
import threading
import time
from urllib.parse import urlparse

from fastapi import Request, Response

from . import config
from .errors import TranscriptionError

COOKIE = "freevideo_session"
_lock = threading.Lock()
_rates: dict[str, list[float]] = {}


def _secret() -> bytes:
    if config.SESSION_SECRET:
        if len(config.SESSION_SECRET) < 32:
            raise TranscriptionError("SESSION_CONFIG", "会话密钥需至少 32 字符，请联系管理员", status=503)
        return config.SESSION_SECRET.encode()
    # Persist a generated development secret outside the public downloads directory.
    with _lock:
        path = config.ASR_DIR / "session.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(secrets.token_hex(32), encoding="ascii")
        return path.read_bytes()


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise TranscriptionError("INVALID_ORIGIN", "请从本站页面发起转写", status=403)
    if origin:
        parsed = urlparse(origin)
        same_host = parsed.scheme in ("http", "https") and parsed.netloc == request.headers.get("host")
        if origin.rstrip("/") not in config.ALLOWED_ORIGINS and not same_host:
            raise TranscriptionError("INVALID_ORIGIN", "请求来源不受信任", status=403)


def owner(request: Request, response: Response | None = None) -> str:
    token = request.cookies.get(COOKIE, "")
    if len(token) <= 180 and token.count(".") == 2:
        session_id, expires, signature = token.split(".")
        payload = session_id + "." + expires
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if (re.fullmatch(r"[a-f0-9]{32}", session_id) and expires.isdigit()
                and int(expires) > time.time() and hmac.compare_digest(signature, expected)):
            return hashlib.sha256(session_id.encode()).hexdigest()
    if response is None:
        raise TranscriptionError("NOT_FOUND", "任务不存在或已过期", status=404)
    session_id = secrets.token_hex(16)
    payload = f"{session_id}.{int(time.time()) + 86400}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    response.set_cookie(COOKIE, payload + "." + signature, max_age=86400, httponly=True,
                        secure=config.SESSION_SECURE, samesite="strict", path="/api")
    return hashlib.sha256(session_id.encode()).hexdigest()


def rate_limit(request: Request, session_owner: str):
    # Never trust X-Forwarded-For here. Deploy uvicorn with --no-proxy-headers,
    # unless the proxy IPs are explicitly configured by the operator.
    peer = request.client.host if request.client else "unknown"
    keys = ["session:" + session_owner, "peer:" + peer]
    now = time.monotonic()
    with _lock:
        for key in list(_rates):
            _rates[key] = [t for t in _rates[key] if now - t < 60]
            if not _rates[key]:
                del _rates[key]
        if any(len(_rates.get(k, [])) >= config.ASR_RATE_LIMIT for k in keys):
            raise TranscriptionError("RATE_LIMIT", "转写请求过于频繁，请一分钟后再试", True, 429)
        for key in keys:
            _rates.setdefault(key, []).append(now)
