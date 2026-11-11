"""Account quota transactions; independent from provider cost accounting."""
import calendar
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from . import account_store as store
from .errors import AccountError, TranscriptionError

TZ = timezone(timedelta(hours=8))
DEFAULT_PLANS = [('free', '免费用户', 0, 1800, 0), ('monthly', '月卡会员', 1990, 36000, 1),
                 ('yearly', '年卡会员', 9900, 108000, 12)]


def seed():
    with store._cursor() as cur:
        cur.executemany('INSERT IGNORE INTO membership_plans (code,name,price_cents,monthly_seconds,months) '
                        'VALUES (%s,%s,%s,%s,%s)', DEFAULT_PLANS)


def plans():
    with store._cursor() as cur:
        cur.execute('SELECT * FROM membership_plans ORDER BY monthly_seconds')
        return list(cur.fetchall())


def period(now=None):
    local = (now or store.utcnow().replace(tzinfo=timezone.utc)).astimezone(TZ)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start.strftime('%Y-%m'), start, end


def _lock_user(cur, user_id):
    cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
    if not cur.fetchone():
        raise AccountError('AUTH_REQUIRED', '请先登录', 401)


def _entitlement(cur, user_id):
    now = store.utcnow()
    cur.execute('SELECT * FROM user_memberships WHERE user_id=%s AND starts_at<=%s AND expires_at>%s',
                (user_id, now, now))
    paid = cur.fetchone()
    if paid:
        return dict(code=paid['plan_code'], name=paid['plan_name'], monthly_seconds=paid['monthly_seconds'],
                    price_cents=paid['price_cents'], revision=paid['revision'], expires_at=paid['expires_at'])
    cur.execute("SELECT * FROM membership_plans WHERE code='free'")
    free = cur.fetchone()
    if not free:
        raise AccountError('PLAN_UNAVAILABLE', '套餐配置暂不可用', 503)
    return {**free, 'expires_at': None}


def _quota(cur, user_id, entitlement):
    month, start, end = period()
    cur.execute('INSERT IGNORE INTO user_quota_periods (user_id,period,plan_code,limit_seconds) VALUES (%s,%s,%s,%s)',
                (user_id, month, entitlement['code'], entitlement['monthly_seconds']))
    cur.execute('SELECT * FROM user_quota_periods WHERE user_id=%s AND period=%s FOR UPDATE', (user_id, month))
    quota = cur.fetchone()
    if quota['plan_code'] != entitlement['code']:
        cur.execute('UPDATE user_quota_periods SET plan_code=%s,limit_seconds=%s WHERE user_id=%s AND period=%s',
                    (entitlement['code'], entitlement['monthly_seconds'], user_id, month))
        quota.update(plan_code=entitlement['code'], limit_seconds=entitlement['monthly_seconds'])
    return quota, start, end


def summary(user_id):
    with store._cursor() as cur:
        _lock_user(cur, user_id)
        ent = _entitlement(cur, user_id)
        quota, start, end = _quota(cur, user_id, ent)
        # Outstanding older holds still reduce what is safe to submit this month.
        cur.execute("SELECT COALESCE(SUM(seconds),0) AS held FROM quota_reservations "
                    "WHERE user_id=%s AND period<>%s AND state IN ('reserved','unknown')", (user_id, quota['period']))
        held = int(cur.fetchone()['held'])
    return dict(plan=ent['code'], name=ent['name'], expires_at=iso(ent['expires_at']),
                limit_seconds=quota['limit_seconds'], used_seconds=quota['used_seconds'],
                reserved_seconds=quota['reserved_seconds'], pending_previous_seconds=held,
                available_seconds=max(0, quota['limit_seconds'] - quota['used_seconds'] - quota['reserved_seconds'] - held),
                period_start=start.isoformat(), resets_at=end.isoformat(), payment_enabled=False)


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def reserve(user_id, job_id, duration, fingerprint):
    if not math.isfinite(duration) or duration <= 0:
        raise TranscriptionError('INVALID_AUDIO', '无法确定识别时长')
    seconds = math.ceil(duration)
    with store._cursor() as cur:
        _lock_user(cur, user_id)
        cur.execute('SELECT * FROM quota_reservations WHERE job_id=%s', (job_id,))
        existing = cur.fetchone()
        if existing:
            if existing['user_id'] == user_id and existing['state'] == 'reserved' and existing['seconds'] == seconds:
                return
            raise TranscriptionError('DUPLICATE_RESERVATION', '该任务已处理，请查询原任务')
        cur.execute("SELECT job_id FROM quota_reservations WHERE user_id=%s AND fingerprint=%s AND state IN ('reserved','unknown')",
                    (user_id, fingerprint))
        if cur.fetchone():
            raise TranscriptionError('SUBMISSION_UNCERTAIN', '相同视频存在执行中或待核对的任务，请查询原任务')
        ent = _entitlement(cur, user_id)
        quota, _, _ = _quota(cur, user_id, ent)
        cur.execute("SELECT COALESCE(SUM(seconds),0) AS held FROM quota_reservations "
                    "WHERE user_id=%s AND period<>%s AND state IN ('reserved','unknown')", (user_id, quota['period']))
        held = int(cur.fetchone()['held'])
        if seconds + quota['used_seconds'] + quota['reserved_seconds'] + held > quota['limit_seconds']:
            raise TranscriptionError('QUOTA_EXCEEDED', '本月语音识别剩余时长不足，请查看个人中心的会员额度', status=403)
        now = store.utcnow()
        cur.execute('INSERT INTO quota_reservations (job_id,user_id,period,seconds,state,fingerprint,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (job_id, user_id, quota['period'], seconds, 'reserved', fingerprint, now))
        cur.execute('UPDATE user_quota_periods SET reserved_seconds=reserved_seconds+%s WHERE user_id=%s AND period=%s',
                    (seconds, user_id, quota['period']))
        cur.execute('INSERT INTO quota_events(job_id,action,seconds,created_at) VALUES (%s,%s,%s,%s)',
                    (job_id, 'reserve', seconds, now))


def finalize(user_id, job_id, state):
    assert state in ('settled', 'released', 'unknown')
    with store._cursor() as cur:
        _lock_user(cur, user_id)
        _finalize(cur, user_id, job_id, state)


def _finalize(cur, user_id, job_id, state):
    cur.execute('SELECT * FROM quota_reservations WHERE job_id=%s AND user_id=%s FOR UPDATE', (job_id, user_id))
    row = cur.fetchone()
    if not row or row['state'] in ('settled', 'released') or row['state'] == state:
        return
    if state != 'unknown':
        cur.execute('UPDATE user_quota_periods SET reserved_seconds=reserved_seconds-%s, used_seconds=used_seconds+%s '
                    'WHERE user_id=%s AND period=%s',
                    (row['seconds'], row['seconds'] if state == 'settled' else 0, user_id, row['period']))
    now = store.utcnow()
    cur.execute('UPDATE quota_reservations SET state=%s,updated_at=%s WHERE job_id=%s', (state, now, job_id))
    cur.execute('INSERT IGNORE INTO quota_events(job_id,action,seconds,created_at) VALUES (%s,%s,%s,%s)',
                (job_id, state, row['seconds'], now))


def complete(job, payload, state):
    """Publish result and settle user seconds in the same transaction."""
    uid = user_id(job.owner)
    if uid is None:
        return
    with store._cursor() as cur:
        _lock_user(cur, uid)
        cur.execute('SELECT id FROM transcription_records WHERE id=%s AND expires_at>%s', (job.id, store.utcnow()))
        if not cur.fetchone():
            raise TranscriptionError('NOT_FOUND', '任务记录已过期', status=404)
        _finalize(cur, uid, job.id, state)
        cur.execute('UPDATE transcription_records SET payload=%s,status=%s,title=%s WHERE id=%s AND user_id=%s',
                    (json.dumps(payload, ensure_ascii=False), payload['status'], payload['title'][:255], job.id, uid))


def user_id(owner):
    return int(owner[5:]) if owner.startswith('user:') else None


def create_record(job):
    uid = user_id(job.owner)
    if uid is None:
        return
    now = store.utcnow()
    with store._cursor() as cur:
        cur.execute('INSERT INTO transcription_records (id,user_id,fingerprint,url,payload,status,created_at,expires_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    (job.id, uid, job.key, job.url, json.dumps(job.public(), ensure_ascii=False), job.status, now, now + timedelta(days=30)))


def persist(job, info=None):
    uid = user_id(job.owner)
    if uid is None:
        return
    with store._cursor() as cur:
        cur.execute('UPDATE transcription_records SET payload=%s,status=%s,title=%s WHERE id=%s AND user_id=%s',
                    (json.dumps(job.public(), ensure_ascii=False), job.status, job.title[:255], job.id, uid))
        if info:
            cur.execute('UPDATE transcription_records SET platform=%s,thumbnail=%s,duration_seconds=%s WHERE id=%s AND user_id=%s',
                        ((info.get('platform') or '')[:64], info.get('thumbnail'), max(0, math.ceil(info.get('duration') or 0)), job.id, uid))


def alias_key(job, fingerprint):
    uid = user_id(job.owner)
    if uid is not None:
        with store._cursor() as cur:
            cur.execute('UPDATE transcription_records SET fingerprint=%s WHERE id=%s AND user_id=%s', (fingerprint, job.id, uid))


def save_alias(job, target_id):
    uid = user_id(job.owner)
    if uid is not None:
        payload = {**job.public(), 'reuse_id': target_id}
        with store._cursor() as cur:
            cur.execute("UPDATE transcription_records SET payload=%s,status='done',hidden=TRUE WHERE id=%s AND user_id=%s",
                        (json.dumps(payload, ensure_ascii=False), job.id, uid))


def record(uid, job_id=None, fingerprint=None):
    with store._cursor() as cur:
        query = 'SELECT * FROM transcription_records WHERE user_id=%s AND expires_at>%s '
        args = [uid, store.utcnow()]
        if job_id:
            query += 'AND id=%s '
            args.append(job_id)
        else:
            query += "AND fingerprint=%s AND (status IN ('done','queued','running') OR JSON_UNQUOTE(JSON_EXTRACT(payload,'$.error_code'))='SUBMISSION_UNCERTAIN') "
            args.append(fingerprint)
        cur.execute(query + 'ORDER BY created_at DESC LIMIT 1', args)
        row = cur.fetchone()
        if row:
            row['payload'] = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        return row


def history(uid, page=1, search='', status='all'):
    with store._cursor() as cur:
        where = 'r.user_id=%s AND r.hidden=FALSE AND r.expires_at>%s'
        args = [uid, store.utcnow()]
        if search:
            where += " AND (r.title LIKE %s OR JSON_UNQUOTE(JSON_EXTRACT(r.payload,'$.result.text')) LIKE %s)"
            args += ['%' + search + '%'] * 2
        if status != 'all':
            where += ' AND r.status IN (%s,%s)' if status == 'active' else ' AND r.status=%s'
            args += ['queued', 'running'] if status == 'active' else [status]
        cur.execute('SELECT COUNT(*) AS total FROM transcription_records r WHERE ' + where, args)
        total = cur.fetchone()['total']
        cur.execute('SELECT r.*, q.state AS quota_state, q.seconds AS quota_seconds FROM transcription_records r '
                    'LEFT JOIN quota_reservations q ON r.id=q.job_id WHERE ' + where +
                    ' ORDER BY r.created_at DESC LIMIT 20 OFFSET %s', args + [(page - 1) * 20])
        rows = list(cur.fetchall())
    for row in rows:
        row['payload'] = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        row.pop('fingerprint', None)
        row.pop('user_id', None)
        row['created_at'] = iso(row['created_at'])
        row['expires_at'] = iso(row['expires_at'])
    return {'items': rows, 'total': total, 'page': page}


def hide(uid, job_id):
    with store._cursor() as cur:
        cur.execute("UPDATE transcription_records SET hidden=TRUE WHERE id=%s AND user_id=%s AND status IN ('done','error')",
                    (job_id, uid))
        if not cur.rowcount:
            raise TranscriptionError('NOT_FOUND', '记录不存在或任务尚未结束', status=404)


def cleanup():
    with store._cursor() as cur:
        cur.execute('DELETE FROM transcription_records WHERE expires_at<=%s', (store.utcnow(),))


def recover(entries, active_ids):
    """Never resend audio after restart; unknown cloud requests retain user holds."""
    with store._cursor() as cur:
        cur.execute("SELECT r.id,r.user_id,r.payload,r.status,q.state FROM transcription_records r "
                    "LEFT JOIN quota_reservations q ON q.job_id=r.id "
                    "WHERE r.status IN ('queued','running') OR q.state IN ('reserved','unknown')")
        rows = list(cur.fetchall())
    for row in rows:
        if row['id'] in active_ids:
            continue
        entry = entries.get(row['id'])
        unknown = entry and entry['state'] in ('submitting', 'submitted', 'unknown')
        payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        result = payload.get('result')
        if result and (result['source'] != 'asr' or (entry and entry['state'] == 'settled')):
            payload.update(status='done', stage='done', message='提取完成', error=None, error_code=None,
                           retryable=False, finished_at=payload.get('finished_at') or datetime.now().timestamp())
            complete(SimpleNamespace(id=row['id'], owner=f"user:{row['user_id']}"), payload,
                     'settled' if result['source'] == 'asr' else 'released')
            continue
        if row['status'] == 'error' and unknown:
            continue
        finalize(row['user_id'], row['id'], 'unknown' if unknown else 'released')
        payload.update(status='error', stage='error', message='服务中断', finished_at=datetime.now().timestamp(),
                       error='识别状态待核对，已保留额度' if unknown else '服务重启，任务已中断，未扣除用户额度',
                       error_code='SUBMISSION_UNCERTAIN' if unknown else 'INTERRUPTED', retryable=not unknown)
        with store._cursor() as cur:
            cur.execute("UPDATE transcription_records SET status='error',payload=%s WHERE id=%s",
                        (json.dumps(payload, ensure_ascii=False), row['id']))


def grant(username, code):
    """Local operator-only command; never exposed as a public upgrade endpoint."""
    with store._cursor() as cur:
        cur.execute('SELECT id FROM users WHERE username_key=%s FOR UPDATE', (username.lower(),))
        user = cur.fetchone()
        if not user:
            raise ValueError('用户不存在')
        cur.execute('SELECT * FROM membership_plans WHERE code=%s', (code,))
        plan = cur.fetchone()
        if not plan or not plan['months']:
            raise ValueError('请选择 monthly 或 yearly')
        ent = _entitlement(cur, user['id'])
        if ent['code'] != 'free':
            raise ValueError('该用户已有有效会员；暂不支持提前续费或跨档升级')
        now = store.utcnow()
        local = now.replace(tzinfo=timezone.utc).astimezone(TZ)
        month = local.month - 1 + plan['months']
        year, month = local.year + month // 12, month % 12 + 1
        end = local.replace(year=year, month=month, day=min(local.day, calendar.monthrange(year, month)[1]))
        cur.execute('REPLACE INTO user_memberships VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    (user['id'], code, plan['name'], plan['price_cents'], plan['monthly_seconds'], plan['revision'], now,
                     end.astimezone(timezone.utc).replace(tzinfo=None)))
        # Upgrade replaces this month's limit; it does not erase usage or add free quota twice.
        quota, _, _ = _quota(cur, user['id'], plan)
        cur.execute('UPDATE user_quota_periods SET limit_seconds=%s,plan_code=%s WHERE user_id=%s AND period=%s',
                    (plan['monthly_seconds'], code, user['id'], quota['period']))


def configure(code, price_cents, monthly_seconds):
    if code not in ('free', 'monthly', 'yearly') or price_cents < 0 or monthly_seconds <= 0 or (code == 'free' and price_cents):
        raise ValueError('套餐参数无效')
    with store._cursor() as cur:
        cur.execute('UPDATE membership_plans SET price_cents=%s,monthly_seconds=%s,revision=revision+1 WHERE code=%s',
                    (price_cents, monthly_seconds, code))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='本机会员管理（不提供在线支付）')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('plans')
    grant_parser = sub.add_parser('grant')
    grant_parser.add_argument('username')
    grant_parser.add_argument('plan', choices=['monthly', 'yearly'])
    edit = sub.add_parser('configure')
    edit.add_argument('plan', choices=['free', 'monthly', 'yearly'])
    edit.add_argument('--price-cents', type=int, required=True)
    edit.add_argument('--monthly-seconds', type=int, required=True)
    args = parser.parse_args()
    store.init_schema()
    seed()
    if args.command == 'grant':
        grant(args.username, args.plan)
        print('会员已开通')
    elif args.command == 'configure':
        configure(args.plan, args.price_cents, args.monthly_seconds)
        print('套餐配置已更新；已有付费会员权益保持原快照')
    else:
        print(json.dumps(plans(), ensure_ascii=False))
