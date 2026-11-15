"""Per-plan usage limits against the real MySQL test database; AI and media providers are simulated."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import account_store, ai_learning, ai_learning_api, config, main, membership, transcriptions, usage
from app.errors import AccountError, NoSubtitles
from .test_accounts import db, register, query, REAL_INIT_SCHEMA
from .test_learning import _fake_openai, _parse_sse

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason='MYSQL_TEST_DATABASE not configured')
VIDEO = 'https://www.bilibili.com/video/BV1xx411c7m{}'


@pytest.fixture(autouse=True)
def reset_plans(db, monkeypatch):
    query('DELETE FROM membership_plans')
    membership.seed()
    monkeypatch.setattr(config, 'DEEPSEEK_API_KEY', 'k')
    ai_learning_api._peer_hits.clear()
    fake, _ = _fake_openai()
    monkeypatch.setattr(ai_learning, '_client', lambda: fake)


def uid(client):
    response = register(client)
    assert response.status_code == 200, response.text
    return response.json()['user']['id']


def tighten(**columns):
    for name, value in columns.items():
        query(f'UPDATE membership_plans SET {name}=%s WHERE code=%s', (value, 'free'))


def summary(client, n, mode='general'):
    resp = client.post('/api/learn/summary', json={'url': VIDEO.format(n), 'mode': mode, 'title': 'T',
                                                    'transcript': '[00:00:05] 字幕文本'})
    assert resp.status_code == 200
    return _parse_sse(resp.text)


def used(user):
    return query('SELECT COUNT(*) AS n FROM ai_usage_videos WHERE user_id=%s', (user,))[0]['n']


def test_default_plan_limits_and_summary_fields(client):
    plans = {p['code']: p for p in client.get('/api/plans').json()['plans']}
    assert [(p['ai_monthly_limit'], p['batch_max_links'], p['asr_max_minutes'], p['chat_daily_limit'])
            for p in (plans['free'], plans['monthly'], plans['yearly'])] == [(10, 3, 8, 1), (300, 10, 30, 10), (500, 15, 60, 20)]
    uid(client)
    data = client.get('/api/account/membership').json()
    assert (data['ai_limit'], data['ai_used'], data['chat_daily_limit'], data['chat_used_today'],
            data['batch_max_links'], data['asr_max_minutes']) == (10, 0, 1, 0, 3, 8)


def test_video_identity_preserves_content_and_ignores_tracking():
    key = usage.video_key
    assert key('https://www.youtube.com/watch?v=abcdefghijk') == key('https://youtu.be/abcdefghijk?si=share')
    assert key('https://www.youtube.com/watch?v=abcdefghijk') == key('https://www.youtube.com/shorts/abcdefghijk?utm_source=x')
    url = VIDEO.format(1)
    assert key(url) == key(url + '?spm_id_from=share')
    assert key(url) != key(url + '?p=2')
    assert key(url) != key(VIDEO.format(2))


@pytest.mark.parametrize('success_first', [True, False])
def test_concurrent_video_success_survives_other_failure(client, success_first):
    user = uid(client)
    a = usage.ai_begin(user, VIDEO.format(1))
    b = usage.ai_begin(user, VIDEO.format(1))
    if success_first:
        usage.ai_commit(b)
        usage.ai_release(a)
    else:
        usage.ai_release(a)
        assert used(user) == 1
        usage.ai_commit(b)
    assert used(user) == 1
    usage.ai_release(a)
    assert used(user) == 1


def test_all_concurrent_failures_release_one_video(client):
    user = uid(client)
    a = usage.ai_begin(user, VIDEO.format(1))
    b = usage.ai_begin(user, VIDEO.format(1))
    usage.ai_release(a)
    assert used(user) == 1
    usage.ai_release(b)
    assert used(user) == 0


def test_existing_ai_usage_schema_migration_preserves_counts(client):
    user = uid(client)
    usage.ai_commit(usage.ai_begin(user, VIDEO.format(1)))
    query('ALTER TABLE ai_usage_videos DROP COLUMN active_requests, DROP COLUMN succeeded')
    REAL_INIT_SCHEMA()
    row = query('SELECT active_requests,succeeded FROM ai_usage_videos WHERE user_id=%s', (user,))[0]
    assert row == {'active_requests': 0, 'succeeded': 1}
    usage.ai_release(usage.ai_begin(user, VIDEO.format(1)))
    assert used(user) == 1


def test_existing_plan_table_is_migrated_with_defaults(client):
    for column in membership.LIMIT_COLUMNS:
        query(f'ALTER TABLE membership_plans DROP COLUMN {column}')
    REAL_INIT_SCHEMA()
    rows = {r['code']: r for r in query('SELECT * FROM membership_plans')}
    assert [rows[c]['ai_monthly_limit'] for c in ('free', 'monthly', 'yearly')] == [10, 300, 500]
    assert [rows[c]['batch_max_links'] for c in ('free', 'monthly', 'yearly')] == [3, 10, 15]
    assert [rows[c]['asr_max_minutes'] for c in ('free', 'monthly', 'yearly')] == [8, 30, 60]
    assert [rows[c]['chat_daily_limit'] for c in ('free', 'monthly', 'yearly')] == [1, 10, 20]


def test_paid_plans_use_their_own_limits(client):
    user = uid(client)
    assert membership.limits(user)['ai_monthly_limit'] == 10
    membership.grant('alice', 'monthly')
    plan = membership.limits(user)
    assert (plan['ai_monthly_limit'], plan['batch_max_links'], plan['chat_daily_limit']) == (300, 10, 10)
    assert transcriptions.max_seconds(user) == 1800
    assert main.batch_cap(user) == (10, '月卡会员')
    query("UPDATE user_memberships SET plan_code='yearly',plan_name='年卡会员' WHERE user_id=%s", (user,))
    assert transcriptions.max_seconds(user) == 3600
    assert main.batch_cap(user)[0] == 15


def test_ai_limit_counts_distinct_videos_and_failures_are_free(client, monkeypatch):
    user = uid(client)
    tighten(ai_monthly_limit=2)
    assert 'done' in [e for e, _ in summary(client, 1)]
    assert 'done' in [e for e, _ in summary(client, 1, 'study')] and used(user) == 1
    real = ai_learning.summarize_events
    monkeypatch.setattr(ai_learning, 'summarize_events', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    assert 'error' in [e for e, _ in summary(client, 2)] and used(user) == 1
    monkeypatch.setattr(ai_learning, 'summarize_events', real)
    assert 'done' in [e for e, _ in summary(client, 3)] and used(user) == 2
    events = summary(client, 4)
    assert [e for e, _ in events] == ['error'] and '次数已用完' in events[0][1] and used(user) == 2
    assert 'done' in [e for e, _ in summary(client, 3, 'deep')]
    assert client.get('/api/account/membership').json()['ai_used'] == 2


def test_missing_subtitles_do_not_consume_an_ai_count(client, monkeypatch):
    user = uid(client)
    monkeypatch.setattr(ai_learning_api, 'read_subtitles', lambda *a, **k: (_ for _ in ()).throw(NoSubtitles('无字幕')))
    resp = client.post('/api/learn/summary', json={'url': VIDEO.format(7)})
    assert 'need_asr' in [e for e, _ in _parse_sse(resp.text)] and used(user) == 0


def test_mindmap_counts_and_limit_is_http_403(client):
    user = uid(client)
    tighten(ai_monthly_limit=1)
    ok = client.post('/api/learn/mindmap', json={'url': VIDEO.format(1), 'title': 'T', 'summary': 'S'})
    assert ok.status_code == 200 and used(user) == 1
    again = client.post('/api/learn/mindmap', json={'url': VIDEO.format(1), 'title': 'T', 'summary': 'S2'})
    assert again.status_code == 200 and used(user) == 1
    blocked = client.post('/api/learn/mindmap', json={'url': VIDEO.format(2), 'title': 'T', 'summary': 'S'})
    assert blocked.status_code == 403 and blocked.json()['code'] == 'AI_QUOTA_EXCEEDED' and used(user) == 1


def test_cycle_reset_restores_ai_count(client, monkeypatch):
    user = uid(client)
    tighten(ai_monthly_limit=1)
    usage.ai_begin(user, VIDEO.format(1))
    with pytest.raises(AccountError) as exc:
        usage.ai_begin(user, VIDEO.format(2))
    assert exc.value.code == 'AI_QUOTA_EXCEEDED'
    now = account_store.utcnow()
    monkeypatch.setattr(account_store, 'utcnow', lambda: now + timedelta(days=40))
    assert membership.summary(user)['ai_used'] == 0
    usage.ai_begin(user, VIDEO.format(2))


def chat(client, n=1):
    resp = client.post('/api/learn/chat', json={'url': VIDEO.format(n), 'title': 'T', 'transcript': '[00:00:05] 字幕',
                                                 'messages': [{'role': 'user', 'content': '总结一下'}]})
    assert resp.status_code == 200
    return _parse_sse(resp.text)


def today_chat(user):
    rows = query('SELECT used FROM ai_chat_daily WHERE user_id=%s', (user,))
    return rows[0]['used'] if rows else 0


def test_chat_daily_limit_refund_and_rollover(client, monkeypatch):
    user = uid(client)
    tighten(chat_daily_limit=1)
    real = ai_learning.chat_stream
    monkeypatch.setattr(ai_learning, 'chat_stream', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    assert 'error' in [e for e, _ in chat(client)] and today_chat(user) == 0 and used(user) == 0
    monkeypatch.setattr(ai_learning, 'chat_stream', real)
    assert 'done' in [e for e, _ in chat(client)] and today_chat(user) == 1
    blocked = chat(client)
    assert [e for e, _ in blocked] == ['error'] and '今日 AI 追问' in blocked[0][1]
    assert today_chat(user) == 1 and used(user) == 1
    now = account_store.utcnow()
    monkeypatch.setattr(account_store, 'utcnow', lambda: now + timedelta(days=1))
    assert 'done' in [e for e, _ in chat(client)]


def test_batch_link_limits_by_plan(client, monkeypatch):
    user = uid(client)
    tighten(batch_max_links=2)
    monkeypatch.setattr(main.manager, 'submit', lambda *a, **k: SimpleNamespace(to_dict=lambda: {'id': 'ok'}))
    urls = ['https://a.com/1', 'https://a.com/2', 'https://a.com/3']
    blocked = client.post('/api/batch', json={'urls': urls, 'kind': 'audio'})
    assert blocked.status_code == 403 and blocked.json()['code'] == 'BATCH_LIMIT' and '最多批量处理 2 条' in blocked.json()['detail']
    assert client.post('/api/batch', json={'urls': urls[:2], 'kind': 'audio'}).json() == {'id': 'ok'}
    client.get('/api/transcription-session')
    sub = client.post('/api/batch-transcriptions', json={'urls': urls, 'allow_asr': True})
    assert sub.status_code == 403 and sub.json()['code'] == 'BATCH_LIMIT'
    membership.grant('alice', 'monthly')
    assert main.batch_cap(user)[0] == 10
    assert client.post('/api/batch', json={'urls': urls, 'kind': 'audio'}).json() == {'id': 'ok'}


def test_asr_duration_limit_follows_plan(client):
    user = uid(client)
    assert transcriptions.max_seconds(user) == 480
    tighten(asr_max_minutes=5)
    assert transcriptions.max_seconds(user) == 300
    assert transcriptions.max_seconds(None) == config.ASR_MAX_DURATION
    assert '5 分钟' in str(transcriptions.too_long(300))
