"""Site account API: register / login / logout / me and the personal center (/api/auth/*, /api/account/*)."""
from datetime import datetime
import secrets

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from . import account_auth as auth
from . import account_store as store
from . import config, guest, captcha, email_verification, password_reset
from .errors import AccountError


def _no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["accounts"], dependencies=[Depends(_no_store)])


class RegisterReq(BaseModel):
    email: str = Field(max_length=254)
    captcha_id: str = Field(max_length=100)
    captcha_answer: str = Field(max_length=16)
    password: str = Field(max_length=256)
    nickname: str | None = Field(default=None, max_length=64)


class LoginReq(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class VerifyEmailReq(BaseModel):
    token: str = Field(max_length=100)


class ForgotPasswordReq(BaseModel):
    email: str = Field(max_length=254)


class ResetPasswordReq(BaseModel):
    token: str = Field(max_length=100)
    password: str = Field(max_length=256)


class ProfileReq(BaseModel):
    nickname: str = Field(max_length=64)


class PasswordReq(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class DeleteAccountReq(BaseModel):
    password: str = Field(max_length=256)
    confirm_email: str = Field(max_length=254)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat() + "Z"


def public_user(row: dict) -> dict:
    return {"id": row["id"], "username": row["username"], "nickname": row["nickname"],
            "created_at": _iso(row["created_at"]), "email": row.get("email"),
            "email_verified": bool(row.get("email_verified"))}


def device_label(user_agent: str) -> str:
    ua = user_agent or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("MicroMessenger", "微信"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
                    if key in ua), "未知浏览器")
    system = next((name for key, name in (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iPadOS"),
                                          ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Linux", "Linux"))
                   if key in ua), "未知系统")
    return f"{browser} · {system}"


@router.get("/api/auth/captcha")
def image_captcha(request: Request, response: Response):
    return captcha.issue(request, response)


@router.post("/api/auth/register")
def register(req: RegisterReq, request: Request, response: Response):
    auth.check_origin(request)
    captcha.consume(request, req.captcha_id, req.captcha_answer)
    email = auth.normalize_email(req.email)
    auth.validate_password(req.password, email)
    username = 'u_' + secrets.token_hex(12)
    nickname = auth.normalize_nickname(req.nickname) if req.nickname and req.nickname.strip() else email.split('@')[0][:30]
    auth.rate_limit("register:" + auth.peer(request), config.AUTH_REGISTER_RATE_LIMIT, 600, "注册过于频繁，请 10 分钟后再试")
    if config.AUTH_EMAIL_VERIFICATION_REQUIRED:
        email_verification.check_config()
        existing = store.get_email_credentials(email)
        if existing:
            if not existing['email_verified']:
                raise AccountError('EMAIL_PENDING', '该邮箱尚未验证，请使用原注册密码重新发送验证邮件', 409)
            raise AccountError('EMAIL_TAKEN', '该邮箱已被注册', 409)
        user = store.create_user(username, username, nickname, auth.hash_password(req.password), None, email=email, verified=False)
        return email_verification.send(user)
    token, session = auth.new_session(request)
    user = store.create_user(username, username, nickname, auth.hash_password(req.password), session, email=email)
    auth.set_cookie(response, token)
    return {"user": public_user(user), "guest_claimed_seconds": guest.claim(request, user["id"])}


@router.post('/api/auth/resend-verification')
def resend_verification(req: LoginReq, request: Request):
    auth.check_origin(request)
    auth.rate_limit('email-resend:' + auth.peer(request), 5, 600, '重发过于频繁，请稍后再试')
    email = auth.normalize_email(req.email)
    row = store.get_email_credentials(email)
    valid = auth.verify_password(req.password[:128], row['password_hash'] if row else auth._DUMMY_HASH)
    if not row or not valid or len(req.password) > 128:
        raise AccountError('INVALID_CREDENTIALS', '邮箱或密码错误', 400)
    store.ensure_active_user(row)
    return email_verification.send(row)


@router.post('/api/auth/verify-email')
def verify_email(req: VerifyEmailReq, request: Request, response: Response):
    auth.check_origin(request)
    auth.rate_limit('verify-email:' + auth.peer(request), 20, 600)
    token, session = auth.new_session(request)
    user = email_verification.consume(req.token, session)
    auth.set_cookie(response, token)
    return {'user': public_user(user), 'guest_claimed_seconds': guest.claim(request, user['id'])}


@router.post("/api/auth/login")
def login(req: LoginReq, request: Request, response: Response):
    auth.check_origin(request)
    auth.rate_limit("login:" + auth.peer(request), config.AUTH_LOGIN_RATE_LIMIT, 60, "登录过于频繁，请一分钟后再试")
    key = auth.normalize_email(req.email)
    if key and auth.login_blocked(key):
        raise AccountError("RATE_LIMIT", "登录失败次数过多，请 15 分钟后再试", 429)
    row = store.get_email_credentials(key) if key and len(req.password) <= 128 else None
    valid = auth.verify_password(req.password[:128], row["password_hash"] if row else auth._DUMMY_HASH)
    if not (row and valid):
        if key:
            auth.record_login_failure(key)
        raise AccountError("INVALID_CREDENTIALS", "邮箱或密码错误", 401)
    store.ensure_active_user(row)
    if not row.get("email_verified"):
        raise AccountError("EMAIL_NOT_VERIFIED", "请先完成邮箱验证后再登录", 403)
    auth.clear_login_failures(key)
    token, session = auth.new_session(request)
    store.create_session(row["id"], session, row['password_hash'])
    auth.set_cookie(response, token)
    return {"user": public_user(row), "guest_claimed_seconds": guest.claim(request, row["id"])}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.check_origin(request)
    auth.revoke_current(request)
    auth.clear_cookie(response)
    return {"ok": True}


@router.post('/api/auth/forgot-password')
def forgot_password(req: ForgotPasswordReq, request: Request):
    auth.check_origin(request)
    auth.rate_limit('forgot-ip:' + auth.peer(request), 5, 600, '申请过于频繁，请稍后再试')
    email = auth.normalize_email(req.email)
    auth.rate_limit('forgot-email:' + auth.token_hash(email), 1, 60, '请间隔 60 秒后再次申请')
    return password_reset.request_reset(email)


@router.post('/api/auth/reset-password')
def reset_password(req: ResetPasswordReq, request: Request):
    auth.check_origin(request)
    auth.rate_limit('reset-ip:' + auth.peer(request), 10, 600)
    password_reset.reset(req.token, req.password)
    return {'ok': True}


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
    auth.validate_password(req.new_password, user.get("email") or user["username"])
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
    if req.confirm_email.strip().lower() != (user.get("email") or "").lower():
        raise AccountError("CONFIRM_MISMATCH", "请输入正确的邮箱以确认注销", 422)
    _verify_current_password(user, req.password, "delete")
    store.delete_user(user["id"])
    auth.clear_cookie(response)
    return {"ok": True}
