"""Per-plan AI usage: distinct videos per personal cycle and chat questions per Beijing day.

Failures never cost the user: callers release a ticket when no result was produced.
"""
import hashlib
import re
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from dataclasses import dataclass

from . import account_store as store
from . import membership
from .errors import AccountError


@dataclass
class Ticket:
    user_id: int
    period: str
    video_key: str
    created: bool
    finished: bool = False


def video_key(url: str, fallback: str = '') -> str:
    raw = url.strip()
    try:
        u = urlsplit(raw)
        host = (u.hostname or '').lower()
        pairs = parse_qsl(u.query, keep_blank_values=True)
        query = dict(pairs)
        if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtube-nocookie.com'):
            vid = u.path.strip('/').split('/')[-1] if host == 'youtu.be' or u.path.startswith(('/shorts/', '/embed/', '/live/')) else query.get('v', '')
            if re.fullmatch(r'[\w-]{11}', vid):
                raw = 'https://www.youtube.com/watch?v=' + vid
        elif host == 'bilibili.com' or host.endswith('.bilibili.com'):
            match = re.search(r'/(BV[0-9A-Za-z]{10}|av\d+)', u.path)
            if match:
                raw = 'https://www.bilibili.com/video/' + match[1] + ('?p=' + query['p'] if query.get('p', '1') != '1' else '')
        elif host == 'douyin.com' or host.endswith('.douyin.com'):
            match = re.search(r'/video/(\d+)', u.path)
            vid = match[1] if match else query.get('modal_id', '')
            if vid.isdigit(): raw = 'https://www.douyin.com/video/' + vid
        if raw == url.strip() and host:
            pairs = [(k, v) for k, v in pairs if not k.lower().startswith('utm_') and k.lower() not in ('spm_id_from', 'share_source', 'share_medium')]
            raw = urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path, urlencode(sorted(pairs)), ''))
    except ValueError:
        pass
    return hashlib.sha256((raw or 'title:' + fallback.strip()).encode()).hexdigest()


def ai_begin(user_id, url, fallback=''):
    """Count one video per cycle. A video already used this cycle (summary, mind map, chat) is free to reuse."""
    key = video_key(url or '', fallback)
    with store._cursor() as cur:
        user = membership._lock_user(cur, user_id)
        now = store.utcnow()
        ent = membership._entitlement(cur, user_id, now)
        quota, _, _ = membership._quota(cur, user, ent, now)
        period = quota['period']
        cur.execute('SELECT 1 FROM ai_usage_videos WHERE user_id=%s AND period=%s AND video_key=%s', (user_id, period, key))
        if cur.fetchone():
            cur.execute('UPDATE ai_usage_videos SET active_requests=active_requests+1 WHERE user_id=%s AND period=%s AND video_key=%s', (user_id, period, key))
            return Ticket(user_id, period, key, False)
        plan = membership._plan_limits(cur, ent['code'])
        cur.execute('SELECT COUNT(*) AS n FROM ai_usage_videos WHERE user_id=%s AND period=%s', (user_id, period))
        used = int(cur.fetchone()['n'])
        if used >= plan['ai_monthly_limit']:
            raise AccountError('AI_QUOTA_EXCEEDED',
                               f"本期 AI 次数已用完（{used}/{plan['ai_monthly_limit']} 个视频）。同一视频可继续使用，"
                               '下个周期重置，或在定价页升级会员提高次数。', 403)
        cur.execute('INSERT INTO ai_usage_videos (user_id,period,video_key,created_at,active_requests,succeeded) VALUES (%s,%s,%s,%s,1,0)',
                    (user_id, period, key, now))
        return Ticket(user_id, period, key, True)


def ai_release(ticket):
    ai_finish(ticket, False)


def ai_commit(ticket):
    ai_finish(ticket, True)


def ai_finish(ticket, success):
    if ticket is None or ticket.finished:
        return
    with store._cursor() as cur:
        membership._lock_user(cur, ticket.user_id)
        cur.execute('UPDATE ai_usage_videos SET active_requests=GREATEST(1,active_requests)-1, succeeded=GREATEST(succeeded,%s) WHERE user_id=%s AND period=%s AND video_key=%s',
                    (int(success), ticket.user_id, ticket.period, ticket.video_key))
        cur.execute('DELETE FROM ai_usage_videos WHERE user_id=%s AND period=%s AND video_key=%s AND active_requests=0 AND succeeded=0',
                    (ticket.user_id, ticket.period, ticket.video_key))
    ticket.finished = True


def chat_begin(user_id):
    with store._cursor() as cur:
        membership._lock_user(cur, user_id)
        now = store.utcnow()
        ent = membership._entitlement(cur, user_id, now)
        plan = membership._plan_limits(cur, ent['code'])
        day = membership.beijing_day(now)
        cur.execute('SELECT used FROM ai_chat_daily WHERE user_id=%s AND day=%s', (user_id, day))
        row = cur.fetchone()
        used = int(row['used']) if row else 0
        if used >= plan['chat_daily_limit']:
            raise AccountError('CHAT_QUOTA_EXCEEDED',
                               f"今日 AI 追问次数已用完（{used}/{plan['chat_daily_limit']} 条），明天（北京时间 0 点）重置，"
                               '或在定价页升级会员提高次数。', 403)
        cur.execute('INSERT INTO ai_chat_daily (user_id,day,used) VALUES (%s,%s,1) '
                    'ON DUPLICATE KEY UPDATE used=used+1', (user_id, day))
        return (user_id, day)


def chat_release(token):
    if token is None:
        return
    user_id, day = token
    with store._cursor() as cur:
        cur.execute('UPDATE ai_chat_daily SET used=used-1 WHERE user_id=%s AND day=%s AND used>0', (user_id, day))
