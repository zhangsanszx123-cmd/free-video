"""Independent administrative authentication and server-local account recovery CLI."""
import argparse
from datetime import timedelta
from getpass import getpass
import secrets
import threading
import time

from fastapi import Depends, Request, Response

from . import account_auth as passwords
from . import account_store, admin_store, config
from .errors import AccountError

COOKIE = 'freevideo_admin'
COOKIE_PATH = '/api/admin'
_lock = threading.Lock()
_hits = {}
_failures = {}


def reset_limits():
    with _lock:
        _hits.clear()
        _failures.clear()


def _prune(bucket, key, seconds):
    now = time.monotonic()
    hits = [value for value in bucket.get(key, []) if now - value < seconds]
    if hits:
        bucket[key] = hits
    else:
        bucket.pop(key, None)
    return hits


def rate_limit(key, limit, seconds, message='后台操作过于频繁，请稍后再试'):
    with _lock:
        if len(_prune(_hits, key, seconds)) >= limit:
            raise AccountError('ADMIN_RATE_LIMIT', message, 429)
        _hits.setdefault(key, []).append(time.monotonic())


def normalize_username(value):
    value = value.strip()
    if not passwords.USERNAME_RE.fullmatch(value):
        raise AccountError('ADMIN_INVALID_USERNAME', '后台登录名需为 4–32 位字母、数字或下划线', 422)
    return value.lower()


def normalize_nickname(value):
    try:
        return passwords.normalize_nickname(value)
    except AccountError as error:
        raise AccountError('ADMIN_INVALID_NICKNAME', str(error), error.status) from error


def validate_password(value, username=''):
    if not 8 <= len(value) <= 128:
        raise AccountError('ADMIN_INVALID_PASSWORD', '密码长度需为 8–128 个字符', 422)
    if not value.strip():
        raise AccountError('ADMIN_INVALID_PASSWORD', '密码不能全部为空白字符', 422)
    if username and value.lower() == username.lower():
        raise AccountError('ADMIN_INVALID_PASSWORD', '密码不能与后台登录名相同', 422)


def check_origin(request):
    try:
        passwords.check_origin(request)
    except AccountError as error:
        raise AccountError('ADMIN_INVALID_ORIGIN', '请从本站管理后台进行操作', error.status) from error


def new_session(request):
    token = secrets.token_urlsafe(32)
    now = account_store.utcnow()
    return token, dict(id=secrets.token_hex(16), token_hash=passwords.token_hash(token), created_at=now,
                       expires_at=now + timedelta(hours=config.ADMIN_SESSION_HOURS),
                       user_agent=(request.headers.get('user-agent') or '')[:255], ip=passwords.peer(request)[:45])


def set_cookie(response, token):
    response.set_cookie(COOKIE, token, max_age=config.ADMIN_SESSION_HOURS * 3600, httponly=True,
                        secure=config.SESSION_SECURE, samesite='lax', path=COOKIE_PATH)


def clear_cookie(response):
    response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, secure=config.SESSION_SECURE, samesite='lax')


def _token(request):
    value = request.cookies.get(COOKIE, '')
    return value if 20 <= len(value) <= 100 and value.isascii() else None


def current_admin(request):
    token = _token(request)
    if not token:
        return None
    digest = passwords.token_hash(token)
    row = admin_store.session_admin(digest)
    if row:
        if account_store.utcnow() - row['last_seen_at'] >= timedelta(minutes=5):
            admin_store.touch_session(row['session_id'])
        row['_token_hash'] = digest
        row['_request_ip'] = passwords.peer(request)
    return row


def require_admin(request: Request):
    row = current_admin(request)
    if not row:
        raise AccountError('ADMIN_AUTH_REQUIRED', '请先登录管理后台', 401)
    request.state.admin_user = row
    return row


def require_superadmin(admin: dict = Depends(require_admin)):
    if admin['role'] != 'superadmin':
        raise AccountError('ADMIN_FORBIDDEN', '仅超级管理员可以执行此操作', 403)
    return admin


def login(request, username, password):
    rate_limit('login-ip:' + passwords.peer(request), 10, 60, '后台登录过于频繁，请一分钟后再试')
    key = normalize_username(username)
    with _lock:
        if len(_prune(_failures, key, 900)) >= 5:
            raise AccountError('ADMIN_RATE_LIMIT', '后台登录失败次数过多，请 15 分钟后再试', 429)
    row = admin_store.get_credentials(key)
    valid = passwords.verify_password(password[:128], row['password_hash'] if row else passwords._DUMMY_HASH)
    if not row or not valid or len(password) > 128:
        with _lock:
            _failures.setdefault(key, []).append(time.monotonic())
        raise AccountError('ADMIN_INVALID_CREDENTIALS', '后台用户名或密码错误', 401)
    if row['status'] != 'active':
        raise AccountError('ADMIN_DISABLED', '该后台账号已禁用，请联系超级管理员', 403)
    token, session = new_session(request)
    fresh = admin_store.create_session(row['id'], session, row['password_hash'])
    with _lock:
        _failures.pop(key, None)
    return token, admin_store.public_admin(fresh)


def revoke_current(request):
    token = _token(request)
    if token:
        admin_store.revoke_session(passwords.token_hash(token))


def change_password(actor, old_password, new_password):
    rate_limit('password:' + str(actor['id']), 5, 600)
    row = admin_store.get_credentials(actor['username'].lower())
    if not row or len(old_password) > 128 or not passwords.verify_password(old_password, row['password_hash']):
        raise AccountError('ADMIN_WRONG_PASSWORD', '当前密码不正确', 400)
    validate_password(new_password, row['username'])
    if old_password == new_password:
        raise AccountError('ADMIN_INVALID_PASSWORD', '新密码不能与当前密码相同', 422)
    admin_store.change_password(actor, row['password_hash'], passwords.hash_password(new_password))


def _read_password(username):
    password = getpass('设置后台密码（输入不显示）：')
    confirmation = getpass('再次输入后台密码：')
    if password != confirmation:
        raise AccountError('ADMIN_PASSWORD_MISMATCH', '两次输入的密码不一致', 422)
    validate_password(password, username)
    return passwords.hash_password(password)


def main():
    parser = argparse.ArgumentParser(description='FreeVideo 管理后台本机初始化和密码恢复')
    commands = parser.add_subparsers(dest='command', required=True)
    bootstrap = commands.add_parser('bootstrap', help='仅首次创建超级管理员，不覆盖现有账号')
    bootstrap.add_argument('--username', default='admin')
    bootstrap.add_argument('--nickname', default='超级管理员')
    recover = commands.add_parser('reset-password', help='本机重置后台密码并撤销该账号全部后台会话')
    recover.add_argument('--username', required=True)
    args = parser.parse_args()
    try:
        username = normalize_username(args.username)
        nickname = normalize_nickname(args.nickname) if args.command == 'bootstrap' else None
        password_hash = _read_password(username)
        # init_schema ignores CREATE DATABASE and USE; no business data is reset.
        account_store.init_schema()
        admin_store.init_schema()
        if args.command == 'bootstrap':
            admin = admin_store.bootstrap(username, nickname, password_hash)
            print(f"已初始化超级管理员：{admin['username']}")
        else:
            admin = admin_store.cli_reset_password(username, password_hash)
            print(f"已重置后台账号密码并撤销会话：{admin['username']}")
    except AccountError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
