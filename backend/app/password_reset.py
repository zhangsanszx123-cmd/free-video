"""Durable single-use email password recovery, bound to the current credentials."""
from datetime import timedelta
import hashlib
import secrets
from . import account_auth as auth, account_store as store, email_verification as mail, config
from .errors import AccountError

INVALID = '重置链接无效或已过期，请重新申请找回密码'
ACCEPTED = {'ok': True, 'message': '如果该邮箱已注册，我们会发送密码重置邮件，请检查收件箱或垃圾邮件。'}


def request_reset(email: str):
    mail.check_config()
    user = store.get_email_credentials(email)
    if not user or user.get('status', 'active') != 'active':
        return ACCEPTED
    token = secrets.token_urlsafe(32)
    digest = auth.token_hash(token)
    now = store.utcnow()
    with store._cursor() as cur:
        cur.execute('SELECT password_hash,status FROM users WHERE id=%s FOR UPDATE', (user['id'],))
        row = cur.fetchone()
        if not row or row.get('status', 'active') != 'active':
            return ACCEPTED
        cur.execute('SELECT created_at FROM password_resets WHERE user_id=%s', (user['id'],))
        previous = cur.fetchone()
        if previous and now - previous['created_at'] < timedelta(seconds=60):
            return ACCEPTED
        credential_hash = hashlib.sha256(row['password_hash'].encode()).hexdigest()
        cur.execute('REPLACE INTO password_resets (user_id,token_hash,credential_hash,created_at,expires_at) VALUES (%s,%s,%s,%s,%s)',
                    (user['id'], digest, credential_hash, now, now + timedelta(minutes=30)))
    try:
        mail.send_email(email, config.PUBLIC_BASE_URL.rstrip('/') + '/reset-password#token=' + token, password_reset=True)
    except AccountError:
        with store._cursor() as cur:
            cur.execute('UPDATE password_resets SET expires_at=%s WHERE token_hash=%s', (now, digest))
        # Keep the same response for unknown accounts and delivery failures to avoid account enumeration.
        # The UI gives a retry/support path; no automatic retries are made.
    return ACCEPTED


def reset(token: str, password: str):
    if len(token) != 43 or not token.isascii():
        raise AccountError('INVALID_RESET_LINK', INVALID, 400)
    digest = auth.token_hash(token)
    with store._cursor() as cur:
        cur.execute('SELECT user_id FROM password_resets WHERE token_hash=%s', (digest,))
        lookup = cur.fetchone()
        if not lookup:
            raise AccountError('INVALID_RESET_LINK', INVALID, 400)
        cur.execute('SELECT id,email,password_hash,email_verified,status FROM users WHERE id=%s FOR UPDATE', (lookup['user_id'],))
        user = cur.fetchone()
        cur.execute('SELECT credential_hash,expires_at FROM password_resets WHERE user_id=%s AND token_hash=%s FOR UPDATE', (lookup['user_id'], digest))
        row = cur.fetchone()
        if (not user or user.get('status', 'active') != 'active' or not row or row['expires_at'] <= store.utcnow()
                or row['credential_hash'] != hashlib.sha256(user['password_hash'].encode()).hexdigest()):
            raise AccountError('INVALID_RESET_LINK', INVALID, 400)
        auth.validate_password(password, user['email'])
        if auth.verify_password(password, user['password_hash']):
            raise AccountError('INVALID_PASSWORD', '新密码不能与原密码相同', 422)
        now = store.utcnow()
        cur.execute('UPDATE users SET password_hash=%s,password_changed_at=%s,updated_at=%s,created_at=IF(email_verified=0,%s,created_at),email_verified=1 WHERE id=%s',
                    (auth.hash_password(password), now, now, now, user['id']))
        cur.execute('DELETE FROM sessions WHERE user_id=%s', (user['id'],))
        cur.execute('DELETE FROM password_resets WHERE user_id=%s', (user['id'],))
        cur.execute('DELETE FROM email_verifications WHERE user_id=%s', (user['id'],))
    auth.clear_login_failures(user['email'])
