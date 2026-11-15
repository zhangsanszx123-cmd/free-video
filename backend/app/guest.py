"""Guest (not logged in) allowance: parse and download at most LIMIT distinct links, ever.

A guest is tracked by a signed cookie AND by IP; either one reaching the limit blocks new links, so clearing
cookies does not help. The video duration of those links is charged to the account's speech-recognition
quota the first time the guest's browser logs in or registers.
"""
import hashlib
import hmac
import logging
import math
import secrets

from fastapi import Request, Response

from . import account_store as store
from . import config, downloader, membership, transcription_auth
from .errors import AccountError

log = logging.getLogger("freevideo.guest")
COOKIE = "freevideo_guest"
LIMIT = 2
LOGIN_HINT = "游客可免费解析并下载 2 个视频，登录后不限次数"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sign(guest_id: str) -> str:
    return hmac.new(transcription_auth._secret(), ("guest:" + guest_id).encode(), hashlib.sha256).hexdigest()


def _cookie_subject(request: Request):
    guest_id, _, signature = (request.cookies.get(COOKIE) or "").partition(".")
    if guest_id and signature and hmac.compare_digest(signature, _sign(guest_id)):
        return "c:" + guest_id
    return None


def _ip_subject(request: Request) -> str:
    return "i:" + (request.client.host if request.client else "unknown")


def _subjects(request: Request) -> list[str]:
    return [s for s in (_cookie_subject(request), _ip_subject(request)) if s]


def _limit_error() -> AccountError:
    return AccountError("GUEST_LIMIT", f"{LOGIN_HINT}。游客的 {LIMIT} 个视频名额已用完，请登录后继续", 403)


def _known(cur, subject, *keys) -> bool:
    cur.execute("SELECT 1 FROM guest_links WHERE subject=%s AND (link_key IN %s OR raw_key IN %s) LIMIT 1",
                (subject, keys, keys))
    return cur.fetchone() is not None


def _count(cur, subject) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM guest_links WHERE subject=%s", (subject,))
    return int(cur.fetchone()["n"])


def begin(request: Request, url: str) -> str:
    """Before parsing: refuse a new link once the guest is out of allowance. Returns the link's raw key."""
    raw = _digest(downloader.extract_url(url))
    with store._cursor() as cur:
        for subject in _subjects(request):
            if not _known(cur, subject, raw) and _count(cur, subject) >= LIMIT:
                raise _limit_error()
    return raw


def record(request: Request, response: Response, raw: str, info: dict):
    """After a successful parse: remember the canonical link (and its duration) for cookie and IP."""
    canonical = _digest(info.get("url") or "")
    duration = max(0, math.ceil(info.get("duration") or 0))
    cookie = _cookie_subject(request)
    if not cookie:
        guest_id = secrets.token_hex(16)
        response.set_cookie(COOKIE, f"{guest_id}.{_sign(guest_id)}", max_age=10 * 365 * 86400, httponly=True,
                            secure=config.SESSION_SECURE, samesite="lax", path="/api")
        cookie = "c:" + guest_id
    subjects = sorted({cookie, _ip_subject(request)})
    with store._cursor() as cur:
        # Serialize concurrent parses of one guest so two parallel requests cannot exceed the limit.
        for subject in subjects:
            cur.execute("SELECT GET_LOCK(%s, 5)", ("fvg:" + subject,))
        try:
            for subject in subjects:
                if _known(cur, subject, raw, canonical):
                    continue
                if _count(cur, subject) >= LIMIT:
                    raise _limit_error()
                cur.execute("INSERT INTO guest_links (subject,link_key,raw_key,duration_seconds,created_at) "
                            "VALUES (%s,%s,%s,%s,%s)", (subject, canonical, raw, duration, store.utcnow()))
        finally:
            for subject in subjects:
                cur.execute("SELECT RELEASE_LOCK(%s)", ("fvg:" + subject,))


def require_known(request: Request, url: str):
    """Guests may only download links they already parsed within their allowance."""
    key = _digest(downloader.extract_url(url))
    with store._cursor() as cur:
        if any(_known(cur, subject, key) for subject in _subjects(request)):
            return
    raise AccountError("GUEST_LIMIT", f"请先解析链接再下载。{LOGIN_HINT}", 403)


def login_required(feature: str = "该功能") -> AccountError:
    return AccountError("AUTH_REQUIRED", f"登录后可使用{feature}。{LOGIN_HINT}", 401)


def claim(request: Request, user_id: int) -> int:
    """First login of this browser: charge the guest's downloaded video seconds to the user's current quota."""
    subject = _cookie_subject(request)
    if not subject:
        return 0
    try:
        with store._cursor() as cur:
            user = membership._lock_user(cur, user_id)
            cur.execute("SELECT link_key,duration_seconds FROM guest_links WHERE subject=%s AND claimed_by IS NULL FOR UPDATE",
                        (subject,))
            rows = list(cur.fetchall())
            if not rows:
                return 0
            now = store.utcnow()
            ent = membership._entitlement(cur, user_id, now)
            quota, _, _ = membership._quota(cur, user, ent, now)
            total = sum(int(r["duration_seconds"]) for r in rows)
            room = max(0, quota["limit_seconds"] - quota["used_seconds"] - quota["reserved_seconds"])
            charged = min(total, room)
            cur.execute("UPDATE user_quota_periods SET used_seconds=used_seconds+%s WHERE user_id=%s AND period=%s",
                        (charged, user_id, quota["period"]))
            cur.execute("UPDATE guest_links SET claimed_by=%s, claimed_seconds=duration_seconds WHERE subject=%s AND claimed_by IS NULL",
                        (user_id, subject))
            return charged
    except AccountError:
        log.warning("guest usage could not be merged into the account quota")
        return 0
