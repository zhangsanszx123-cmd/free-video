"""Independent admin identities and transactional management of site accounts."""
import json
from datetime import timezone
import re

from . import account_store as store
from .errors import AccountError

ADMIN_FIELDS = 'a.id,a.username,a.nickname,a.role,a.status,a.created_at'
PAGE_SIZE = 20
ROLES = ('superadmin', 'admin')
STATUSES = ('active', 'disabled')


def _iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')


def public_admin(row):
    return {**{key: row[key] for key in ('id', 'username', 'nickname', 'role', 'status')},
            'created_at': _iso(row['created_at'])}


def init_schema():
    """Create only admin tables; never execute CREATE DATABASE/USE or seed credentials."""
    statements = store.SCHEMA_FILE.read_text(encoding='utf-8').split(';')
    with store._cursor() as cur:
        for sql in statements:
            body = '\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--')).strip()
            if re.match(r'CREATE TABLE IF NOT EXISTS admin_[a-z_]+\s*\(', body, re.I):
                cur.execute(body)
        cur.execute('INSERT IGNORE INTO admin_account_guard (id) VALUES (1)')


def _guard(cur):
    cur.execute('SELECT id FROM admin_account_guard WHERE id=1 FOR UPDATE')
    if not cur.fetchone():
        raise AccountError('ADMIN_UNAVAILABLE', '后台服务暂不可用，请稍后再试', 503)


def _lock_admins(cur, ids):
    cur.execute(f'SELECT {ADMIN_FIELDS},a.password_hash FROM admin_users a '
                'WHERE a.id IN %s ORDER BY a.id FOR UPDATE', (tuple(sorted(set(ids))),))
    return {row['id']: row for row in cur.fetchall()}


def _auth_required():
    return AccountError('ADMIN_AUTH_REQUIRED', '后台登录已失效，请重新登录', 401)


def _lock_actor(cur, actor, *, superadmin=False, target_id=None):
    """Guard -> admins in ID order -> actor session -> optional site user/tokens."""
    _guard(cur)
    ids = [actor['id']] + ([target_id] if target_id is not None else [])
    rows = _lock_admins(cur, ids)
    current = rows.get(actor['id'])
    if not current or current['status'] != 'active':
        raise _auth_required()
    cur.execute('SELECT id FROM admin_sessions WHERE admin_id=%s AND token_hash=%s AND expires_at>%s FOR UPDATE',
                (actor['id'], actor.get('_token_hash', ''), store.utcnow()))
    if not cur.fetchone():
        raise _auth_required()
    if superadmin and current['role'] != 'superadmin':
        raise AccountError('ADMIN_FORBIDDEN', '仅超级管理员可以管理后台账号', 403)
    return current, rows


def _audit(cur, actor, action, target_type, target, *, before=None, after=None, reason=''):
    detail = {key: value for key, value in [('before', before), ('after', after), ('reason', reason)] if value}
    cur.execute('INSERT INTO admin_audit_logs '
                '(actor_id,actor_username,action,target_type,target_id,target_label,detail,ip,created_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (actor.get('id') if actor else None, actor.get('username', 'server-cli') if actor else 'server-cli',
                 action, target_type, target['id'], target.get('email') or target.get('username') or str(target['id']),
                 json.dumps(detail, ensure_ascii=False), (actor.get('_request_ip', '') if actor else 'local-cli')[:45],
                 store.utcnow()))


def get_credentials(username_key):
    with store._cursor() as cur:
        cur.execute(f'SELECT {ADMIN_FIELDS},a.password_hash FROM admin_users a WHERE a.username_key=%s', (username_key,))
        return cur.fetchone()


def get_staff(admin_id):
    with store._cursor() as cur:
        cur.execute(f'SELECT {ADMIN_FIELDS} FROM admin_users a WHERE a.id=%s', (admin_id,))
        row = cur.fetchone()
    if not row:
        raise AccountError('ADMIN_NOT_FOUND', '后台账号不存在', 404)
    return public_admin(row)


def create_session(admin_id, session, expected_password_hash):
    """Recheck credentials/status under the same row lock used by revocation."""
    with store._cursor() as cur:
        rows = _lock_admins(cur, [admin_id])
        row = rows.get(admin_id)
        if not row or row['password_hash'] != expected_password_hash:
            raise AccountError('ADMIN_INVALID_CREDENTIALS', '后台用户名或密码错误', 401)
        if row['status'] != 'active':
            raise AccountError('ADMIN_DISABLED', '该后台账号已禁用，请联系超级管理员', 403)
        cur.execute('DELETE FROM admin_sessions WHERE admin_id=%s AND expires_at<=%s', (admin_id, store.utcnow()))
        cur.execute('INSERT INTO admin_sessions '
                    '(id,token_hash,admin_id,created_at,last_seen_at,expires_at,user_agent,ip) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    (session['id'], session['token_hash'], admin_id, session['created_at'], session['created_at'],
                     session['expires_at'], session['user_agent'], session['ip']))
    return row


def session_admin(token_hash):
    with store._cursor() as cur:
        cur.execute(f'SELECT {ADMIN_FIELDS},s.id AS session_id,s.last_seen_at FROM admin_sessions s '
                    "JOIN admin_users a ON a.id=s.admin_id WHERE s.token_hash=%s AND s.expires_at>%s AND a.status='active'",
                    (token_hash, store.utcnow()))
        return cur.fetchone()


def touch_session(session_id):
    with store._cursor() as cur:
        cur.execute('UPDATE admin_sessions SET last_seen_at=%s WHERE id=%s', (store.utcnow(), session_id))


def revoke_session(token_hash):
    with store._cursor() as cur:
        cur.execute('DELETE FROM admin_sessions WHERE token_hash=%s', (token_hash,))


def _pattern(text):
    return '%' + text.replace('=', '==').replace('%', '=%').replace('_', '=_') + '%'


def _numeric_id(text):
    if text.isascii() and text.isdigit() and len(text) <= 20:
        value = int(text)
        if 0 < value <= 18446744073709551615:
            return value
    return None


def list_staff(page=1, search='', status='all'):
    where, args = '1=1', []
    if search:
        where += " AND (CONVERT(a.username_key USING utf8mb4) COLLATE utf8mb4_bin LIKE %s ESCAPE '=' OR a.nickname LIKE %s ESCAPE '='"
        args += [_pattern(search.lower()), _pattern(search)]
        identifier = _numeric_id(search)
        if identifier is not None:
            where += ' OR a.id=%s'
            args.append(identifier)
        where += ')'
    if status != 'all':
        where += ' AND a.status=%s'
        args.append(status)
    with store._cursor() as cur:
        cur.execute('SELECT COUNT(*) AS total FROM admin_users a WHERE ' + where, args)
        total = cur.fetchone()['total']
        cur.execute(f'SELECT {ADMIN_FIELDS} FROM admin_users a WHERE ' + where +
                    ' ORDER BY a.created_at DESC,a.id DESC LIMIT %s OFFSET %s', args + [PAGE_SIZE, (page - 1) * PAGE_SIZE])
        items = [public_admin(row) for row in cur.fetchall()]
    return dict(items=items, total=total, page=page, page_size=PAGE_SIZE)


def _insert_staff(cur, username, nickname, password_hash, role, status):
    now = store.utcnow()
    cur.execute('SELECT id FROM admin_users WHERE username_key=%s', (username.lower(),))
    if cur.fetchone():
        raise AccountError('ADMIN_USERNAME_TAKEN', '该后台登录名已存在', 409)
    cur.execute('INSERT INTO admin_users '
                '(username,username_key,nickname,password_hash,role,status,created_at,updated_at,password_changed_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (username, username.lower(), nickname, password_hash, role, status, now, now, now))
    return dict(id=cur.lastrowid, username=username, nickname=nickname, role=role, status=status, created_at=now)


def bootstrap(username, nickname, password_hash):
    with store._cursor() as cur:
        _guard(cur)
        cur.execute('SELECT id FROM admin_users LIMIT 1')
        if cur.fetchone():
            raise AccountError('ADMIN_ALREADY_INITIALIZED', '后台账号已经初始化，不会覆盖现有账号', 409)
        row = _insert_staff(cur, username, nickname, password_hash, 'superadmin', 'active')
        _audit(cur, None, 'staff.bootstrap', 'admin', row, after={'role': 'superadmin', 'status': 'active'})
    return public_admin(row)


def create_staff(actor, username, nickname, password_hash, role='admin', status='active'):
    if role not in ROLES or status not in STATUSES:
        raise AccountError('ADMIN_INVALID_STAFF', '请选择有效的角色和状态', 422)
    with store._cursor() as cur:
        _lock_actor(cur, actor, superadmin=True)
        row = _insert_staff(cur, username, nickname, password_hash, role, status)
        _audit(cur, actor, 'staff.create', 'admin', row, after={'role': role, 'status': status, 'nickname': nickname})
    return public_admin(row)


def update_staff(actor, admin_id, changes):
    if not changes or set(changes) - {'nickname', 'role', 'status'}:
        raise AccountError('ADMIN_INVALID_STAFF', '请提交需要修改的后台账号信息', 422)
    with store._cursor() as cur:
        _, rows = _lock_actor(cur, actor, superadmin=True, target_id=admin_id)
        row = rows.get(admin_id)
        if not row:
            raise AccountError('ADMIN_NOT_FOUND', '后台账号不存在', 404)
        updated = {**row, **changes}
        if updated['role'] not in ROLES or updated['status'] not in STATUSES:
            raise AccountError('ADMIN_INVALID_STAFF', '请选择有效的角色和状态', 422)
        if admin_id == actor['id'] and updated['status'] == 'disabled':
            raise AccountError('ADMIN_SELF_DISABLE', '不能禁用当前登录的后台账号', 409)
        if row['role'] == 'superadmin' and row['status'] == 'active' and (updated['role'] != 'superadmin' or updated['status'] != 'active'):
            cur.execute("SELECT COUNT(*) AS total FROM admin_users WHERE role='superadmin' AND status='active'")
            if cur.fetchone()['total'] <= 1:
                raise AccountError('ADMIN_LAST_SUPERADMIN', '至少保留一个启用的超级管理员', 409)
        cur.execute('UPDATE admin_users SET nickname=%s,role=%s,status=%s,updated_at=%s WHERE id=%s',
                    (updated['nickname'], updated['role'], updated['status'], store.utcnow(), admin_id))
        if row['role'] != updated['role'] or updated['status'] == 'disabled':
            cur.execute('DELETE FROM admin_sessions WHERE admin_id=%s', (admin_id,))
        fields = ('nickname', 'role', 'status')
        _audit(cur, actor, 'staff.update', 'admin', row,
               before={key: row[key] for key in fields}, after={key: updated[key] for key in fields})
    return public_admin(updated)


def _write_password(cur, row, password_hash):
    now = store.utcnow()
    cur.execute('UPDATE admin_users SET password_hash=%s,password_changed_at=%s,updated_at=%s WHERE id=%s',
                (password_hash, now, now, row['id']))
    cur.execute('DELETE FROM admin_sessions WHERE admin_id=%s', (row['id'],))


def reset_staff_password(actor, admin_id, password_hash):
    with store._cursor() as cur:
        _, rows = _lock_actor(cur, actor, superadmin=True, target_id=admin_id)
        row = rows.get(admin_id)
        if not row:
            raise AccountError('ADMIN_NOT_FOUND', '后台账号不存在', 404)
        _write_password(cur, row, password_hash)
        _audit(cur, actor, 'staff.password_reset', 'admin', row)
    return public_admin(row)


def change_password(actor, expected_password_hash, password_hash):
    with store._cursor() as cur:
        row, _ = _lock_actor(cur, actor)
        if row['password_hash'] != expected_password_hash:
            raise AccountError('ADMIN_WRONG_PASSWORD', '当前密码不正确，请重新输入', 400)
        _write_password(cur, row, password_hash)
        _audit(cur, actor, 'staff.password_change', 'admin', row)


def cli_reset_password(username_key, password_hash):
    with store._cursor() as cur:
        _guard(cur)
        cur.execute(f'SELECT {ADMIN_FIELDS},a.password_hash FROM admin_users a WHERE a.username_key=%s FOR UPDATE', (username_key,))
        row = cur.fetchone()
        if not row:
            raise AccountError('ADMIN_NOT_FOUND', '后台账号不存在', 404)
        _write_password(cur, row, password_hash)
        _audit(cur, None, 'staff.cli_password_reset', 'admin', row)
    return public_admin(row)


_USER_SELECT = ('u.id,u.email,u.nickname,u.created_at,u.email_verified,u.status,u.disabled_at,u.disabled_reason,'
                "COALESCE(m.plan_code,'free') AS membership_plan,"
                "COALESCE(m.plan_name,f.name,'免费用户') AS membership_name,m.expires_at AS membership_expires_at")
_USER_FROM = (" FROM users u LEFT JOIN user_memberships m ON m.user_id=u.id AND m.starts_at<=%s AND m.expires_at>%s "
              "LEFT JOIN membership_plans f ON f.code='free'")


def _public_user(row):
    return {**{key: row[key] for key in ('id', 'email', 'nickname', 'status', 'disabled_reason')},
            'created_at': _iso(row['created_at']), 'email_verified': bool(row['email_verified']),
            'disabled_at': _iso(row['disabled_at']),
            'membership': dict(plan=row['membership_plan'], name=row['membership_name'], expires_at=_iso(row['membership_expires_at']))}


def _get_user(cur, user_id):
    now = store.utcnow()
    cur.execute('SELECT ' + _USER_SELECT + _USER_FROM + ' WHERE u.id=%s', (now, now, user_id))
    row = cur.fetchone()
    if not row:
        raise AccountError('ADMIN_USER_NOT_FOUND', '注册用户不存在', 404)
    return _public_user(row)


def get_user(user_id):
    with store._cursor() as cur:
        return _get_user(cur, user_id)


def list_users(page=1, search='', status='all', verified='all'):
    where, args = '1=1', []
    if search:
        where += " AND (CONVERT(u.email USING utf8mb4) COLLATE utf8mb4_bin LIKE %s ESCAPE '=' OR u.nickname LIKE %s ESCAPE '='"
        args += [_pattern(search.lower()), _pattern(search)]
        identifier = _numeric_id(search)
        if identifier is not None:
            where += ' OR u.id=%s'
            args.append(identifier)
        where += ')'
    if status != 'all':
        where += ' AND u.status=%s'
        args.append(status)
    if verified != 'all':
        where += ' AND u.email_verified=%s'
        args.append(1 if verified == 'verified' else 0)
    with store._cursor() as cur:
        cur.execute('SELECT COUNT(*) AS total FROM users u WHERE ' + where, args)
        total = cur.fetchone()['total']
        now = store.utcnow()
        cur.execute('SELECT ' + _USER_SELECT + _USER_FROM + ' WHERE ' + where +
                    ' ORDER BY u.created_at DESC,u.id DESC LIMIT %s OFFSET %s',
                    [now, now] + args + [PAGE_SIZE, (page - 1) * PAGE_SIZE])
        items = [_public_user(row) for row in cur.fetchall()]
    return dict(items=items, total=total, page=page, page_size=PAGE_SIZE)


def set_user_status(actor, user_id, status, reason=''):
    reason = reason.strip()
    if status not in STATUSES or len(reason) > 500:
        raise AccountError('ADMIN_INVALID_STATUS', '请选择有效状态，原因最多 500 个字符', 422)
    with store._cursor() as cur:
        _lock_actor(cur, actor)
        cur.execute('SELECT id,email,status,disabled_at,disabled_reason FROM users WHERE id=%s FOR UPDATE', (user_id,))
        row = cur.fetchone()
        if not row:
            raise AccountError('ADMIN_USER_NOT_FOUND', '注册用户不存在', 404)
        now = store.utcnow()
        disabled_at = (row['disabled_at'] or now) if status == 'disabled' else None
        stored_reason = reason if status == 'disabled' else ''
        cur.execute('UPDATE users SET status=%s,disabled_at=%s,disabled_reason=%s,updated_at=%s WHERE id=%s',
                    (status, disabled_at, stored_reason, now, user_id))
        if status == 'disabled':
            cur.execute('DELETE FROM sessions WHERE user_id=%s', (user_id,))
            cur.execute('DELETE FROM email_verifications WHERE user_id=%s', (user_id,))
            cur.execute('DELETE FROM password_resets WHERE user_id=%s', (user_id,))
        _audit(cur, actor, 'user.disable' if status == 'disabled' else 'user.enable', 'user', row,
               before={'status': row['status']}, after={'status': status}, reason=reason)
        result = _get_user(cur, user_id)
    return result
