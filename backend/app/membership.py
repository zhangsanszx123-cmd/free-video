"""Account quota transactions; independent from provider cost accounting."""
import calendar
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from . import account_store as store
from . import zpay
from .errors import AccountError, TranscriptionError

TZ = timezone(timedelta(hours=8))
DEFAULT_PLANS = [('free', '免费用户', 0, 1800, 0), ('monthly', '月卡会员', 1990, 36000, 1),
                 ('yearly', '年卡会员', 9900, 108000, 12)]
LIMIT_COLUMNS = ('ai_monthly_limit', 'batch_max_links', 'asr_max_minutes', 'chat_daily_limit')


def seed():
    limits_by_code = {row[0]: row[1:] for row in store.DEFAULT_LIMITS}
    rows = [plan + limits_by_code[plan[0]] for plan in DEFAULT_PLANS]
    with store._cursor() as cur:
        cur.executemany('INSERT IGNORE INTO membership_plans (code,name,price_cents,monthly_seconds,months,'
                        + ','.join(LIMIT_COLUMNS) + ') VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', rows)


def beijing_day(now=None):
    now = now if now is not None else store.utcnow()
    return now.replace(tzinfo=timezone.utc).astimezone(TZ).date()


def _plan_limits(cur, code):
    cur.execute('SELECT * FROM membership_plans WHERE code=%s', (code,))
    plan = cur.fetchone()
    if not plan:
        raise AccountError('PLAN_UNAVAILABLE', '套餐配置暂不可用', 503)
    return dict(plan=plan['code'], name=plan['name'], ai_monthly_limit=plan['ai_monthly_limit'],
                batch_max_links=plan['batch_max_links'], asr_max_minutes=plan['asr_max_minutes'],
                chat_daily_limit=plan['chat_daily_limit'])


def limits(user_id):
    """Usage limits of the user's current plan (read live from the plan table, not snapshotted)."""
    with store._cursor() as cur:
        return _plan_limits(cur, _entitlement(cur, user_id)['code'])


def plans():
    with store._cursor() as cur:
        cur.execute('SELECT * FROM membership_plans ORDER BY monthly_seconds')
        return list(cur.fetchall())


def period(anchor, now=None):
    """Monthly anniversaries of the original UTC-naive anchor, with Beijing month-end clamping.

    Always calculate from the original date: Jan 31 -> Feb 28 -> Mar 31, not Mar 28.
    Boundaries are [start, end), including the anchor's time of day and microseconds.
    """
    now = now if now is not None else store.utcnow()
    local = now.replace(tzinfo=timezone.utc).astimezone(TZ)
    origin = anchor.replace(tzinfo=timezone.utc).astimezone(TZ)
    months = (local.year - origin.year) * 12 + local.month - origin.month
    if months_after(anchor, months) > now:
        months -= 1
    months = max(0, months)
    start, end = months_after(anchor, months), months_after(anchor, months + 1)
    return start.isoformat(timespec='microseconds'), start, end


def _lock_user(cur, user_id):
    cur.execute('SELECT id,created_at FROM users WHERE id=%s FOR UPDATE', (user_id,))
    user = cur.fetchone()
    if not user:
        raise AccountError('AUTH_REQUIRED', '请先登录', 401)
    return user


def _entitlement(cur, user_id, now=None):
    now = now if now is not None else store.utcnow()
    cur.execute('SELECT * FROM user_memberships WHERE user_id=%s AND starts_at<=%s AND expires_at>%s',
                (user_id, now, now))
    paid = cur.fetchone()
    if paid:
        cur.execute('SELECT monthly_seconds FROM membership_plans WHERE code=%s', (paid['plan_code'],))
        live = cur.fetchone()
        if not live:
            raise AccountError('PLAN_UNAVAILABLE', '套餐配置暂不可用', 503)
        return dict(code=paid['plan_code'], name=paid['plan_name'], monthly_seconds=live['monthly_seconds'],
                    price_cents=paid['price_cents'], revision=paid['revision'],
                    starts_at=paid['starts_at'], expires_at=paid['expires_at'])
    cur.execute("SELECT * FROM membership_plans WHERE code='free'")
    free = cur.fetchone()
    if not free:
        raise AccountError('PLAN_UNAVAILABLE', '套餐配置暂不可用', 503)
    return {**free, 'expires_at': None}


def _quota(cur, user, entitlement, now):
    paid = entitlement['code'] != 'free'
    anchor = entitlement['starts_at'] if paid else user['created_at']
    key, start, end = period(anchor, now)
    # Free and Pro periods never share usage, even when their starting timestamps coincide.
    key = ('pro:' if paid else 'free:') + key
    if paid:
        end = min(end, entitlement['expires_at'])
    user_id = user['id']
    cur.execute('INSERT IGNORE INTO user_quota_periods (user_id,period,plan_code,limit_seconds) VALUES (%s,%s,%s,%s)',
                (user_id, key, entitlement['code'], entitlement['monthly_seconds']))
    cur.execute('SELECT * FROM user_quota_periods WHERE user_id=%s AND period=%s FOR UPDATE', (user_id, key))
    quota = cur.fetchone()
    if quota['plan_code'] != entitlement['code'] or quota['limit_seconds'] != entitlement['monthly_seconds']:
        cur.execute('UPDATE user_quota_periods SET plan_code=%s,limit_seconds=%s WHERE user_id=%s AND period=%s',
                    (entitlement['code'], entitlement['monthly_seconds'], user_id, key))
        quota.update(plan_code=entitlement['code'], limit_seconds=entitlement['monthly_seconds'])
    return quota, start, end


def summary(user_id):
    with store._cursor() as cur:
        user = _lock_user(cur, user_id)
        now = store.utcnow()
        ent = _entitlement(cur, user_id, now)
        quota, start, end = _quota(cur, user, ent, now)
        # Outstanding older holds still reduce what is safe to submit in this cycle.
        cur.execute("SELECT COALESCE(SUM(seconds),0) AS held FROM quota_reservations "
                    "WHERE user_id=%s AND period<>%s AND state IN ('reserved','unknown')", (user_id, quota['period']))
        held = int(cur.fetchone()['held'])
        plan_limits = _plan_limits(cur, ent['code'])
        cur.execute('SELECT COUNT(*) AS n FROM ai_usage_videos WHERE user_id=%s AND period=%s', (user_id, quota['period']))
        ai_used = int(cur.fetchone()['n'])
        cur.execute('SELECT used FROM ai_chat_daily WHERE user_id=%s AND day=%s', (user_id, beijing_day(now)))
        chat_row = cur.fetchone()
    return dict(plan=ent['code'], name=ent['name'], expires_at=iso(ent['expires_at']),
                ai_limit=plan_limits['ai_monthly_limit'], ai_used=ai_used,
                chat_daily_limit=plan_limits['chat_daily_limit'], chat_used_today=int(chat_row['used']) if chat_row else 0,
                batch_max_links=plan_limits['batch_max_links'], asr_max_minutes=plan_limits['asr_max_minutes'],
                limit_seconds=quota['limit_seconds'], used_seconds=quota['used_seconds'],
                reserved_seconds=quota['reserved_seconds'], pending_previous_seconds=held,
                available_seconds=max(0, quota['limit_seconds'] - quota['used_seconds'] - quota['reserved_seconds'] - held),
                period_start=iso(start), period_end=iso(end), resets_at=iso(end),
                reset_basis='registration' if ent['code'] == 'free' else 'membership',
                ends_with_membership=ent['expires_at'] == end, payment_enabled=zpay.enabled())


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def reserve(user_id, job_id, duration, fingerprint):
    if not math.isfinite(duration) or duration <= 0:
        raise TranscriptionError('INVALID_AUDIO', '无法确定识别时长')
    seconds = math.ceil(duration)
    with store._cursor() as cur:
        user = _lock_user(cur, user_id)
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
        now = store.utcnow()
        ent = _entitlement(cur, user_id, now)
        quota, _, _ = _quota(cur, user, ent, now)
        cur.execute("SELECT COALESCE(SUM(seconds),0) AS held FROM quota_reservations "
                    "WHERE user_id=%s AND period<>%s AND state IN ('reserved','unknown')", (user_id, quota['period']))
        held = int(cur.fetchone()['held'])
        if seconds + quota['used_seconds'] + quota['reserved_seconds'] + held > quota['limit_seconds']:
            raise TranscriptionError('QUOTA_EXCEEDED', '本期语音识别剩余时长不足，请查看个人中心的会员额度', status=403)
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
    """Account history, or all visible history when trusted admin code passes uid=None."""
    with store._cursor() as cur:
        where = 'r.hidden=FALSE AND r.expires_at>%s'
        args = [store.utcnow()]
        if uid is not None:
            where += ' AND r.user_id=%s'
            args.append(uid)
        if search:
            where += " AND (r.title LIKE %s OR JSON_UNQUOTE(JSON_EXTRACT(r.payload,'$.result.text')) LIKE %s)"
            args += ['%' + search + '%'] * 2
        if status != 'all':
            where += ' AND r.status IN (%s,%s)' if status == 'active' else ' AND r.status=%s'
            args += ['queued', 'running'] if status == 'active' else [status]
        cur.execute('SELECT COUNT(*) AS total FROM transcription_records r WHERE ' + where, args)
        total = cur.fetchone()['total']
        owner_select = ',u.email AS user_email' if uid is None else ''
        owner_join = ' LEFT JOIN users u ON u.id=r.user_id ' if uid is None else ' '
        cur.execute('SELECT r.*, q.state AS quota_state, q.seconds AS quota_seconds' + owner_select + ' FROM transcription_records r '
                    'LEFT JOIN quota_reservations q ON r.id=q.job_id' + owner_join + 'WHERE ' + where +
                    ' ORDER BY r.created_at DESC,r.id DESC LIMIT 20 OFFSET %s', args + [(page - 1) * 20])
        rows = list(cur.fetchall())
    for row in rows:
        row['payload'] = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        row.pop('fingerprint', None)
        if uid is not None:
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
        cur.execute('SELECT id FROM users WHERE email=%s OR username_key=%s FOR UPDATE', (username.strip().lower(), username.strip().lower()))
        user = cur.fetchone()
        if not user:
            raise ValueError('用户不存在')
        cur.execute('SELECT * FROM membership_plans WHERE code=%s', (code,))
        plan = cur.fetchone()
        if not plan or not plan['months']:
            raise ValueError('请选择 monthly 或 yearly')
        ent = _entitlement(cur, user['id'])
        if ent['code'] != 'free':
            raise ValueError('该用户已有有效会员；请通过在线支付续费或升级')
        now = store.utcnow()
        apply_membership(cur, user['id'], plan, now, months_after(now, plan['months']))


def months_after(start, months):
    """Add calendar months in Beijing time (month-end clamps to the target month's last day). UTC naive in/out."""
    local = start.replace(tzinfo=timezone.utc).astimezone(TZ)
    month = local.month - 1 + months
    year, month = local.year + month // 12, month % 12 + 1
    end = local.replace(year=year, month=month, day=min(local.day, calendar.monthrange(year, month)[1]))
    return end.astimezone(timezone.utc).replace(tzinfo=None)


def renewal_expiry(starts_at, expires_at, months):
    """Keep month-end renewals on their original anniversary when expiry is a cycle boundary."""
    _, boundary, _ = period(starts_at, expires_at)
    if boundary == expires_at:
        origin = starts_at.replace(tzinfo=timezone.utc).astimezone(TZ)
        expiry = expires_at.replace(tzinfo=timezone.utc).astimezone(TZ)
        elapsed = (expiry.year - origin.year) * 12 + expiry.month - origin.month
        return months_after(starts_at, elapsed + months)
    # Upgrades can carry an extra remainder; preserve that existing expiry calculation.
    return months_after(expires_at, months)


def apply_membership(cur, uid, plan, starts_at, expires_at):
    """Write the purchase snapshot; caller holds the user row lock. Quotas use the live plan.

    A new membership starts a full Pro cycle. Renewal/upgrade retain the existing anchor
    and current Pro usage; free allowance is never added to the paid limit.
    """
    code = plan.get('code') or plan['plan_code']
    name = plan.get('name') or plan['plan_name']
    cur.execute('REPLACE INTO user_memberships VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                (uid, code, name, plan['price_cents'], plan['monthly_seconds'], plan['revision'], starts_at, expires_at))
    now = store.utcnow()
    _quota(cur, _lock_user(cur, uid), _entitlement(cur, uid, now), now)


def configure(code, price_cents, monthly_seconds, **limit_values):
    if code not in ('free', 'monthly', 'yearly') or price_cents < 0 or monthly_seconds <= 0 or (code == 'free' and price_cents):
        raise ValueError('套餐参数无效')
    changes = {k: v for k, v in limit_values.items() if v is not None}
    if set(changes) - set(LIMIT_COLUMNS) or any(v < 1 for v in changes.values()):
        raise ValueError('套餐参数无效')
    with store._cursor() as cur:
        cur.execute('UPDATE membership_plans SET price_cents=%s,monthly_seconds=%s,revision=revision+1 WHERE code=%s',
                    (price_cents, monthly_seconds, code))
        for column, value in changes.items():
            cur.execute(f'UPDATE membership_plans SET {column}=%s WHERE code=%s', (value, code))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='本机会员管理（人工开通，不经过支付）')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('plans')
    grant_parser = sub.add_parser('grant')
    grant_parser.add_argument('username')
    grant_parser.add_argument('plan', choices=['monthly', 'yearly'])
    edit = sub.add_parser('configure')
    edit.add_argument('plan', choices=['free', 'monthly', 'yearly'])
    edit.add_argument('--price-cents', type=int, required=True)
    edit.add_argument('--monthly-seconds', type=int, required=True)
    for column in LIMIT_COLUMNS:
        edit.add_argument('--' + column.replace('_', '-'), type=int)
    args = parser.parse_args()
    store.init_schema()
    seed()
    if args.command == 'grant':
        grant(args.username, args.plan)
        print('会员已开通')
    elif args.command == 'configure':
        configure(args.plan, args.price_cents, args.monthly_seconds,
                  **{column: getattr(args, column) for column in LIMIT_COLUMNS})
        print('套餐配置已更新；额度立即影响已有用户，已用量与预占保留')
    else:
        print(json.dumps(plans(), ensure_ascii=False))
