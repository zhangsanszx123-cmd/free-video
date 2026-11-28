"""Developer credentials and account-scoped API task grants; never store cleartext keys."""
import hashlib
import json
import secrets
import uuid
from datetime import timedelta

from . import account_store as store, membership
from .errors import AccountError

KEY_FIELDS = 'id,name,prefix,created_at,last_used_at,revoked_at'


def _user(cur, uid):
    cur.execute('SELECT id,status,email_verified,password_hash FROM users WHERE id=%s FOR UPDATE', (uid,))
    user = cur.fetchone()
    if not user or user['status'] != 'active' or not user['email_verified']:
        raise AccountError('API_KEY_INVALID', 'API 密钥无效或已撤销', 401)
    return user


def _paid(cur, uid):
    if membership._entitlement(cur, uid)['code'] not in ('monthly', 'yearly'):
        raise AccountError('API_MEMBERSHIP_REQUIRED', '开放 API 仅向有效月卡、年卡会员开放', 403)


def credential_digest(user):
    return hashlib.sha256(user['password_hash'].encode()).hexdigest()


def public_key(row):
    return {k: membership.iso(row[k]) if k.endswith('_at') else row[k]
            for k in KEY_FIELDS.split(',')}


def keys(uid):
    with store._cursor() as cur:
        _user(cur, uid)
        entitled = membership._entitlement(cur, uid)['code'] in ('monthly', 'yearly')
        cur.execute(f'SELECT {KEY_FIELDS} FROM open_api_keys WHERE user_id=%s ORDER BY revoked_at IS NOT NULL,created_at DESC LIMIT 100', (uid,))
        return {'eligible': entitled, 'max_keys': 3, 'keys': [public_key(r) for r in cur.fetchall()]}


def create_key(uid, session_id, name):
    name = name.strip()
    if not 1 <= len(name) <= 50 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise AccountError('INVALID_KEY_NAME', '密钥名称需为 1–50 个字符，不能含控制字符', 422)
    token = 'fv_live_' + secrets.token_urlsafe(32)
    now = store.utcnow()
    row = dict(id=uuid.uuid4().hex, name=name, prefix=token[:16], created_at=now, last_used_at=None, revoked_at=None)
    with store._cursor() as cur:
        user = _user(cur, uid)
        # A stale website session may not mint credentials after a concurrent reset.
        cur.execute('SELECT id FROM sessions WHERE id=%s AND user_id=%s AND expires_at>%s', (session_id, uid, now))
        if not cur.fetchone():
            raise AccountError('AUTH_REQUIRED', '请重新登录后创建密钥', 401)
        _paid(cur, uid)
        cur.execute('SELECT COUNT(*) AS n FROM open_api_keys WHERE user_id=%s AND revoked_at IS NULL', (uid,))
        if cur.fetchone()['n'] >= 3:
            raise AccountError('API_KEY_LIMIT', '最多保留 3 把有效密钥，请先撤销旧密钥', 403)
        cur.execute('INSERT INTO open_api_keys (id,user_id,name,token_hash,credential_hash,prefix,created_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (row['id'], uid, name, hashlib.sha256(token.encode()).hexdigest(), credential_digest(user), row['prefix'], now))
    return {'key': public_key(row), 'token': token}


def revoke_key(uid, key_id):
    with store._cursor() as cur:
        _user(cur, uid)
        cur.execute('SELECT id FROM open_api_keys WHERE id=%s AND user_id=%s', (key_id, uid))
        if not cur.fetchone():
            raise AccountError('NOT_FOUND', '密钥不存在', 404)
        cur.execute('UPDATE open_api_keys SET revoked_at=COALESCE(revoked_at,%s) WHERE id=%s', (store.utcnow(), key_id))


def _valid(cur, user, key_id):
    cur.execute('SELECT id,credential_hash FROM open_api_keys WHERE id=%s AND user_id=%s AND revoked_at IS NULL', (key_id, user['id']))
    key = cur.fetchone()
    if not key or not secrets.compare_digest(key['credential_hash'], credential_digest(user)):
        raise AccountError('API_KEY_INVALID', 'API 密钥无效或已撤销', 401)


def authenticate(digest):
    with store._cursor() as cur:
        cur.execute('SELECT id,user_id FROM open_api_keys WHERE token_hash=%s', (digest,))
        key = cur.fetchone()
        if not key:
            raise AccountError('API_KEY_INVALID', 'API 密钥无效或已撤销', 401)
        user = _user(cur, key['user_id'])
        _valid(cur, user, key['id'])
        now = store.utcnow()
        cur.execute('UPDATE open_api_keys SET last_used_at=%s WHERE id=%s AND '
                    '(last_used_at IS NULL OR last_used_at<%s)', (now, key['id'], now - timedelta(minutes=5)))
        return {'user_id': user['id'], 'key_id': key['id']}


def _decode(row):
    if row and isinstance(row.get('failure'), str):
        row['failure'] = json.loads(row['failure'])
    return row


def lookup(uid, task_id):
    with store._cursor() as cur:
        cur.execute('SELECT * FROM open_api_requests WHERE id=%s AND user_id=%s AND expires_at>%s', (task_id, uid, store.utcnow()))
        return _decode(cur.fetchone())


def admit(principal, idem, digest):
    """Serialize admission by account. Release SQL locks before touching manager locks."""
    uid = principal['user_id']
    now = store.utcnow()
    with store._cursor() as cur:
        user = _user(cur, uid)
        _valid(cur, user, principal['key_id'])
        # Previously accepted operations remain readable even when membership expires.
        cur.execute('SELECT * FROM open_api_requests WHERE user_id=%s AND idempotency_key=%s', (uid, idem))
        old = _decode(cur.fetchone())
        if old:
            if old['expires_at'] <= now:
                raise AccountError('IDEMPOTENCY_EXPIRED', '幂等记录已过期，请使用新的幂等键', 409)
            if old['request_hash'] != digest:
                raise AccountError('IDEMPOTENCY_CONFLICT', '同一幂等键不能用于不同请求参数', 409)
            return old, False
        _paid(cur, uid)
        cur.execute("SELECT COUNT(DISTINCT COALESCE(t.id,r.id,a.transcription_id)) AS n FROM open_api_requests a "
                    "LEFT JOIN transcription_records r ON r.id=a.transcription_id AND r.user_id=a.user_id "
                    "LEFT JOIN transcription_records t ON t.id=JSON_UNQUOTE(JSON_EXTRACT(r.payload,'$.reuse_id')) AND t.user_id=a.user_id "
                    "WHERE a.user_id=%s AND a.expires_at>%s AND (a.state='submitting' OR "
                    "(a.state='submitted' AND COALESCE(t.status,r.status) IN ('queued','running')))", (uid, now))
        if cur.fetchone()['n'] >= 2:
            raise AccountError('API_CONCURRENCY_LIMIT', '最多同时处理 2 个 API 任务，请稍后再试', 429)
        row = dict(id=uuid.uuid4().hex, user_id=uid, key_id=principal['key_id'], idempotency_key=idem,
                   request_hash=digest, transcription_id=uuid.uuid4().hex, state='submitting', failure=None,
                   created_at=now, expires_at=now + timedelta(days=30))
        cur.execute('INSERT INTO open_api_requests (id,user_id,key_id,idempotency_key,request_hash,transcription_id,state,created_at,expires_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', tuple(row[k] for k in
                    ('id', 'user_id', 'key_id', 'idempotency_key', 'request_hash', 'transcription_id', 'state', 'created_at', 'expires_at')))
        return row, True


def bind(row, job):
    """Called under the manager lock BEFORE enqueue or returning a deduplicated job."""
    with store._cursor() as cur:
        cur.execute('SELECT expires_at FROM transcription_records WHERE id=%s AND user_id=%s', (job.id, row['user_id']))
        saved = cur.fetchone()
        expires = min(row['expires_at'], saved['expires_at']) if saved else row['expires_at']
        cur.execute("UPDATE open_api_requests SET transcription_id=%s,state='submitted',expires_at=%s WHERE id=%s AND user_id=%s",
                    (job.id, expires, row['id'], row['user_id']))
        row.update(transcription_id=job.id, state='submitted', expires_at=expires)


def fail(row, code, message, retryable=False):
    failure = dict(code=code, message=message, retryable=retryable)
    with store._cursor() as cur:
        cur.execute("UPDATE open_api_requests SET state='failed',failure=%s WHERE id=%s AND user_id=%s",
                    (json.dumps(failure, ensure_ascii=False), row['id'], row['user_id']))
    row.update(state='failed', failure=failure)


def recover():
    # Never enqueue here: a crash may have happened just after accepting a cloud request.
    with store._cursor() as cur:
        cur.execute("UPDATE open_api_requests a LEFT JOIN transcription_records r ON r.id=a.transcription_id AND r.user_id=a.user_id "
                    "SET a.state=IF(r.id IS NULL,'failed','submitted'),a.failure=IF(r.id IS NULL,%s,NULL) WHERE a.state='submitting'",
                    (json.dumps(dict(code='INTERRUPTED', message='任务接收中断，未入队；请使用新幂等键重试', retryable=True), ensure_ascii=False),))

