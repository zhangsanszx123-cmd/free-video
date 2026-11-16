"""SMTP delivery and durable, one-use registration verification links."""
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import secrets
import smtplib
import ssl
from urllib.parse import urlsplit

from . import config, account_store as store, account_auth as auth
from .errors import AccountError


def check_config():
    url = urlsplit(config.PUBLIC_BASE_URL)
    local = url.hostname in ('localhost', '127.0.0.1', '::1')
    if (not config.SMTP_HOST or not config.SMTP_USER or not config.SMTP_PASSWORD
            or url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or (url.scheme != 'https' and not local) or url.query or url.fragment):
        raise AccountError('EMAIL_UNAVAILABLE', '验证邮件服务暂不可用，请稍后再试', 503)


def send_email(recipient: str, link: str, *, password_reset: bool = False):
    message = EmailMessage()
    message['Subject'] = '重置你的 FreeVideo 登录密码' if password_reset else '验证你的 FreeVideo 注册邮箱'
    message['From'] = config.SMTP_FROM
    message['To'] = recipient
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid()
    local_note = '\n本机测试链接只能在运行网站的电脑上访问。' if urlsplit(config.PUBLIC_BASE_URL).hostname in ('localhost', '127.0.0.1', '::1') else ''
    introduction = '你正在找回 FreeVideo 登录密码。\n\n请在 30 分钟内打开以下链接，设置新密码：\n' if password_reset else '你正在注册 FreeVideo 万能视频下载器。\n\n请在 30 分钟内打开以下链接，并点击页面中的确认按钮完成注册：\n'
    message.set_content(introduction + link + '\n\n如果不是你本人操作，请忽略此邮件。请勿转发此链接。' + local_note)
    accepted = False
    try:
        context = ssl.create_default_context()
        if config.SMTP_SSL:
            smtp = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=15, context=context)
        else:
            smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
        with smtp:
            if not config.SMTP_SSL:
                smtp.starttls(context=context)
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            if smtp.send_message(message):
                raise AccountError('EMAIL_SEND_FAILED', '验证邮件未能发送，请稍后重发', 503)
            accepted = True
    except (smtplib.SMTPException, OSError):
        if accepted:
            return  # A failed QUIT does not invalidate a message already accepted for delivery.
        # Never expose credentials, token URLs, server responses, or recipient details in logs.
        raise AccountError('EMAIL_SEND_FAILED', '验证邮件未能确认发送，请稍后尝试重发', 503) from None


def send(user: dict):
    check_config()
    token = secrets.token_urlsafe(32)
    digest = auth.token_hash(token)
    now = store.utcnow()
    with store._cursor() as cur:
        cur.execute('SELECT email_verified,status FROM users WHERE id=%s FOR UPDATE', (user['id'],))
        row = cur.fetchone()
        store.ensure_active_user(row)
        if not row or row['email_verified']:
            raise AccountError('EMAIL_ALREADY_VERIFIED', '该账号已验证，请直接登录', 409)
        cur.execute('SELECT created_at FROM email_verifications WHERE user_id=%s', (user['id'],))
        previous = cur.fetchone()
        if previous and now - previous['created_at'] < timedelta(seconds=60):
            raise AccountError('RATE_LIMIT', '请间隔 60 秒后再重发验证邮件', 429)
        cur.execute('REPLACE INTO email_verifications (user_id,token_hash,created_at,expires_at) VALUES (%s,%s,%s,%s)',
                    (user['id'], digest, now, now + timedelta(minutes=30)))
    link = config.PUBLIC_BASE_URL.rstrip('/') + '/verify-email#token=' + token
    try:
        send_email(user['email'], link)
    except AccountError:
        with store._cursor() as cur:
            # Leave cooldown in place but invalidate this failed delivery only.
            cur.execute('UPDATE email_verifications SET expires_at=%s WHERE token_hash=%s', (now, digest))
        raise
    return {'verification_required': True, 'email': user['email'], 'resend_after': 60}


def consume(token: str, session: dict):
    if len(token) != 43 or not token.isascii():
        raise AccountError('INVALID_VERIFICATION_LINK', '验证链接无效或已过期，请重新发送', 400)
    digest = auth.token_hash(token)
    with store._cursor() as cur:
        # Lookup first, then lock user before token, matching send() lock order.
        cur.execute('SELECT user_id FROM email_verifications WHERE token_hash=%s', (digest,))
        lookup = cur.fetchone()
        if not lookup:
            raise AccountError('INVALID_VERIFICATION_LINK', '验证链接无效或已过期，请重新发送', 400)
        cur.execute(f'SELECT {store.USER_FIELDS} FROM users u WHERE u.id=%s FOR UPDATE', (lookup['user_id'],))
        user = cur.fetchone()
        store.ensure_active_user(user)
        cur.execute('SELECT expires_at FROM email_verifications WHERE user_id=%s AND token_hash=%s FOR UPDATE', (lookup['user_id'], digest))
        row = cur.fetchone()
        if not user or user['email_verified'] or not row or row['expires_at'] <= store.utcnow():
            raise AccountError('INVALID_VERIFICATION_LINK', '验证链接无效或已过期，请重新发送', 400)
        now = store.utcnow()
        cur.execute('UPDATE users SET email_verified=1,created_at=%s,updated_at=%s WHERE id=%s', (now, now, user['id']))
        cur.execute('DELETE FROM email_verifications WHERE user_id=%s', (user['id'],))
        store._insert_session(cur, user['id'], session)
    return {**user, 'email_verified': True, 'created_at': now}
