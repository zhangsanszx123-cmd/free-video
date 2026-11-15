"""Site account API: register / login / logout / me and the personal center (/api/auth/*, /api/account/*)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from . import account_auth as auth
from . import account_store as store
from . import config, guest
from .errors import AccountError


def _no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["accounts"], dependencies=[Depends(_no_store)])


class RegisterReq(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    nickname: str | None = Field(default=None, max_length=64)


class LoginReq(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class ProfileReq(BaseModel):
    nickname: str = Field(max_length=64)


class PasswordReq(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class DeleteAccountReq(BaseModel):
    password: str = Field(max_length=256)
    confirm_username: str = Field(max_length=64)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat() + "Z"


def public_user(row: dict) -> dict:
    return {"id": row["id"], "username": row["username"], "nickname": row["nickname"],
            "created_at": _iso(row["created_at"])}


def device_label(user_agent: str) -> str:
    ua = user_agent or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("MicroMessenger", "微信"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
                    if key in ua), "未知浏览器")
    system = next((name for key, name in (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iPadOS"),
                                          ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Linux", "Linux"))
                   if key in ua), "未知系统")
    return f"{browser} · {system}"


@router.post("/api/auth/register")
def register(req: RegisterReq, request: Request, response: Response):
    auth.check_origin(request)
    key = auth.normalize_username(req.username)
    auth.validate_password(req.password, req.username)
    nickname = auth.normalize_nickname(req.nickname) if req.nickname and req.nickname.strip() else req.username
    auth.rate_limit("register:" + auth.peer(request), config.AUTH_REGISTER_RATE_LIMIT, 600, "注册过于频繁，请 10 分钟后再试")
    token, session = auth.new_session(request)
    user = store.create_user(req.username, key, nickname, auth.hash_password(req.password), session)
    auth.set_cookie(response, token)
    return {"user": public_user(user), "guest_claimed_seconds": guest.claim(request, user["id"])}


@router.post("/api/auth/login")
def login(req: LoginReq, request: Request, response: Response):
    auth.check_origin(request)
    auth.rate_limit("login:" + auth.peer(request), config.AUTH_LOGIN_RATE_LIMIT, 60, "登录过于频繁，请一分钟后再试")
    key = req.username.lower() if auth.USERNAME_RE.fullmatch(req.username) else None
    if key and auth.login_blocked(key):
        raise AccountError("RATE_LIMIT", "登录失败次数过多，请 15 分钟后再试", 429)
    row = store.get_credentials(key) if key and len(req.password) <= 128 else None
    valid = auth.verify_password(req.password[:128], row["password_hash"] if row else auth._DUMMY_HASH)
    if not (row and valid):
        if key:
            auth.record_login_failure(key)
        raise AccountError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
    auth.clear_login_failures(key)
    token, session = auth.new_session(request)
    store.create_session(row["id"], session)
    auth.set_cookie(response, token)
    return {"user": public_user(row), "guest_claimed_seconds": guest.claim(request, row["id"])}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.check_origin(request)
    auth.revoke_current(request)
    auth.clear_cookie(response)
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request, response: Response):
    user = auth.current_user(request)
    if not user and auth.COOKIE in request.cookies:
        auth.clear_cookie(response)
    return {"user": public_user(user) if user else None}


@router.patch("/api/account/profile")
def update_profile(req: ProfileReq, request: Request, user: dict = Depends(auth.require_user)):
    auth.check_origin(request)
    nickname = auth.normalize_nickname(req.nickname)
    store.update_nickname(user["id"], nickname)
    return {"user": public_user({**user, "nickname": nickname})}


def _verify_current_password(user: dict, password: str, action: str):
    auth.rate_limit(f"{action}:{user['id']}", 5, 600, "尝试次数过多，请 10 分钟后再试")
    stored = store.get_password_hash(user["id"])
    if not stored or len(password) > 128 or not auth.verify_password(password, stored):
        raise AccountError("WRONG_PASSWORD", "当前密码不正确", 400)


@router.post("/api/account/password")
def change_password(req: PasswordReq, request: Request, response: Response, user: dict = Depends(auth.require_user)):
    auth.check_origin(request)
    _verify_current_password(user, req.old_password, "password")
    auth.validate_password(req.new_password, user["username"])
    if req.new_password == req.old_password:
        raise AccountError("INVALID_PASSWORD", "新密码不能与当前密码相同", 422)
    store.update_password(user["id"], auth.hash_password(req.new_password))
    auth.clear_cookie(response)
    return {"ok": True}


@router.get("/api/account/sessions")
def sessions(user: dict = Depends(auth.require_user)):
    return {"sessions": [{"id": s["id"], "device": device_label(s["user_agent"]), "ip": s["ip"],
                          "created_at": _iso(s["created_at"]), "last_seen_at": _iso(s["last_seen_at"]),
                          "expires_at": _iso(s["expires_at"]), "current": s["id"] == user["session_id"]}
                         for s in store.list_sessions(user["id"])]}


@router.post("/api/account/sessions/revoke-others")
def revoke_other_sessions(request: Request, user: dict = Depends(auth.require_user)):
    auth.check_origin(request)
    return {"revoked": store.delete_other_sessions(user["id"], user["session_id"])}


@router.delete("/api/account/sessions/{session_id}")
def revoke_session(session_id: str, request: Request, response: Response, user: dict = Depends(auth.require_user)):
    auth.check_origin(request)
    if not store.delete_session(user["id"], session_id[:32]):
        raise AccountError("NOT_FOUND", "该登录设备不存在或已下线", 404)
    current = session_id == user["session_id"]
    if current:
        auth.clear_cookie(response)
    return {"ok": True, "current": current}


@router.delete("/api/account")
def delete_account(req: DeleteAccountReq, request: Request, response: Response, user: dict = Depends(auth.require_user)):
    auth.check_origin(request)
    if req.confirm_username.lower() != user["username"].lower():
        raise AccountError("CONFIRM_MISMATCH", "请输入正确的用户名以确认注销", 422)
    _verify_current_password(user, req.password, "delete")
    store.delete_user(user["id"])
    auth.clear_cookie(response)
    return {"ok": True}
