"""Real MySQL quota/history tests; all media and provider calls are simulated."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import uuid
import threading

import pytest
from fastapi.testclient import TestClient

from app import account_store, asr, config, main, membership, transcriptions
from app.asr import Recognition
from app.errors import AccountError, TranscriptionError
from .test_accounts import db, register, login, query, PASSWORD, REAL_INIT_SCHEMA
from .test_transcriptions import cloud, wait, SAMPLE

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason='MYSQL_TEST_DATABASE not configured')


@pytest.fixture(autouse=True)
def reset_plans(db):
    query('DELETE FROM membership_plans')
    membership.seed()


def uid(client):
    response = register(client)
    assert response.status_code == 200, response.text
    return response.json()['user']['id']


def job_id():
    return uuid.uuid4().hex


def hold(user, seconds, fingerprint=None):
    job = job_id()
    membership.reserve(user, job, seconds, fingerprint or job.ljust(64, '0'))
    return job


def test_default_plans_and_auth(client):
    assert [p['monthly_seconds'] for p in client.get('/api/plans').json()['plans']] == [1800, 36000, 108000]
    assert [p['price_cents'] for p in client.get('/api/plans').json()['plans']] == [0, 1990, 9900]
    assert client.get('/api/account/membership').status_code == 401
    assert client.get('/api/account/history').status_code == 401
    user = uid(client)
    summary = client.get('/api/account/membership').json()
    assert summary['available_seconds'] == 1800 and summary['payment_enabled'] is False
    assert client.post('/api/plans', json={}).status_code == 405
    assert membership.summary(user)['used_seconds'] == 0


def test_anniversary_boundary_and_cross_period_finalization(client, monkeypatch):
    user = uid(client)
    anchor = datetime(2026, 10, 20, 2, 30, 0, 123456)
    query('UPDATE users SET created_at=%s WHERE id=%s', (anchor, user))
    boundary = datetime(2026, 11, 20, 2, 30, 0, 123456)
    monkeypatch.setattr(account_store, 'utcnow', lambda: boundary - timedelta(microseconds=1))
    original = membership.summary(user)
    assert original['period_start'] == membership.iso(anchor)
    assert original['resets_at'] == membership.iso(boundary)
    job = hold(user, 100)
    membership.finalize(user, job, 'unknown')
    monkeypatch.setattr(account_store, 'utcnow', lambda: boundary)
    summary = membership.summary(user)
    assert summary['period_start'] == membership.iso(boundary)
    assert summary['resets_at'] == membership.iso(datetime(2026, 12, 20, 2, 30, 0, 123456))
    assert summary['used_seconds'] == 0 and summary['pending_previous_seconds'] == 100
    assert summary['available_seconds'] == 1700
    membership.finalize(user, job, 'settled')
    assert membership.summary(user)['available_seconds'] == 1800
    assert query('SELECT used_seconds FROM user_quota_periods WHERE user_id=%s AND period=%s',
                 (user, 'free:' + anchor.isoformat(timespec='microseconds')))[0]['used_seconds'] == 100


def test_concurrent_reservations_cannot_overspend(client):
    user = uid(client)
    def attempt(_):
        try:
            return hold(user, 1200)
        except TranscriptionError as e:
            assert e.code == 'QUOTA_EXCEEDED'
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [job for job in pool.map(attempt, range(6)) if job]
    assert len(jobs) == 1
    assert membership.summary(user)['available_seconds'] == 600


def test_rounding_idempotency_and_event_audit(client):
    user = uid(client)
    job = hold(user, 1.01)
    fingerprint = job.ljust(64, '0')
    membership.reserve(user, job, 1.01, fingerprint)
    assert membership.summary(user)['reserved_seconds'] == 2
    membership.finalize(user, job, 'unknown')
    membership.finalize(user, job, 'settled')
    membership.finalize(user, job, 'settled')
    membership.finalize(user, job, 'released')
    assert membership.summary(user)['used_seconds'] == 2
    assert membership.summary(user)['reserved_seconds'] == 0
    assert len(query('SELECT * FROM quota_events WHERE job_id=%s', (job,))) == 3


def test_unresolved_same_video_blocks_retry(client):
    user = uid(client)
    fingerprint = 'f' * 64
    job = hold(user, 60, fingerprint)
    membership.finalize(user, job, 'unknown')
    with pytest.raises(TranscriptionError, match='待核对'):
        hold(user, 60, fingerprint)
    assert membership.summary(user)['reserved_seconds'] == 60


def test_grant_config_snapshot_and_expiry(client, monkeypatch):
    user = uid(client)
    assert membership.summary(user)['limit_seconds'] == 1800
    used = hold(user, 60)
    membership.finalize(user, used, 'settled')
    membership.grant('alice@example.com', 'monthly')
    assert membership.summary(user)['available_seconds'] == 36000
    paid = hold(user, 120)
    membership.finalize(user, paid, 'settled')
    membership.configure('monthly', 2990, 72000)
    assert membership.summary(user)['limit_seconds'] == 72000
    assert membership.summary(user)['used_seconds'] == 120
    with pytest.raises(ValueError, match='已有有效会员'):
        membership.grant('alice@example.com', 'yearly')
    query('UPDATE user_memberships SET expires_at=%s WHERE user_id=%s', (account_store.utcnow() - timedelta(seconds=1), user))
    assert membership.summary(user)['limit_seconds'] == 1800
    assert membership.summary(user)['available_seconds'] == 1740
    membership.grant('alice@example.com', 'yearly')
    assert membership.summary(user)['limit_seconds'] == 108000
    assert membership.summary(user)['used_seconds'] == 0
    assert membership.summary(user)['available_seconds'] == 108000


def test_free_config_changes_current_cycle(client, monkeypatch):
    monkeypatch.setattr(account_store, 'utcnow', lambda: datetime(2026, 11, 5))
    user = uid(client)
    assert membership.summary(user)['limit_seconds'] == 1800
    membership.configure('free', 0, 3600)
    assert membership.summary(user)['limit_seconds'] == 3600
    monkeypatch.setattr(account_store, 'utcnow', lambda: datetime(2026, 12, 1))
    assert membership.summary(user)['limit_seconds'] == 3600
    monkeypatch.setattr(account_store, 'utcnow', lambda: datetime(2026, 12, 5))
    assert membership.summary(user)['limit_seconds'] == 3600


def test_registration_dates_produce_independent_free_cycles(client, monkeypatch):
    user = uid(client)
    query('UPDATE users SET created_at=%s WHERE id=%s', (datetime(2026, 10, 12, 1, 5), user))
    other = register(client, 'bob_01').json()['user']['id']
    query('UPDATE users SET created_at=%s WHERE id=%s', (datetime(2026, 10, 25, 3, 10), other))
    monkeypatch.setattr(account_store, 'utcnow', lambda: datetime(2026, 11, 15))
    first, second = membership.summary(user), membership.summary(other)
    assert first['resets_at'] == membership.iso(datetime(2026, 12, 12, 1, 5))
    assert second['resets_at'] == membership.iso(datetime(2026, 11, 25, 3, 10))
    assert first['available_seconds'] == second['available_seconds'] == 1800


def test_pro_anniversary_ignores_registration_day_and_month_start(client, monkeypatch):
    user = uid(client)
    query('UPDATE users SET created_at=%s WHERE id=%s', (datetime(2026, 10, 5, 2), user))
    opening = datetime(2026, 11, 20, 4, 15)
    monkeypatch.setattr(account_store, 'utcnow', lambda: opening)
    free = hold(user, 600)
    membership.finalize(user, free, 'settled')
    membership.grant('alice@example.com', 'yearly')
    initial = membership.summary(user)
    assert initial['limit_seconds'] == initial['available_seconds'] == 108000
    assert initial['period_start'] == membership.iso(opening)
    assert initial['reset_basis'] == 'membership'
    paid = hold(user, 60)
    membership.finalize(user, paid, 'settled')
    for day in (1, 5, 19):
        monkeypatch.setattr(account_store, 'utcnow', lambda day=day: datetime(2026, 12, day, 4, 15))
        assert membership.summary(user)['available_seconds'] == 107940
    monkeypatch.setattr(account_store, 'utcnow', lambda: datetime(2026, 12, 20, 4, 15))
    renewed = membership.summary(user)
    assert renewed['available_seconds'] == 108000
    assert renewed['used_seconds'] == 0
    assert renewed['resets_at'] == membership.iso(datetime(2027, 1, 20, 4, 15))
    assert not renewed['ends_with_membership']


def test_membership_expiry_restores_registration_cycle_without_double_free_grant(client, monkeypatch):
    user = uid(client)
    query('UPDATE users SET created_at=%s WHERE id=%s', (datetime(2026, 10, 25, 2), user))
    monkeypatch.setattr(account_store, 'utcnow', lambda: datetime(2026, 11, 10, 3))
    membership.grant('alice@example.com', 'monthly')
    # A membership can expire within a registration cycle in which free quota was already used.
    expiry = datetime(2026, 11, 20, 3)
    query('UPDATE user_memberships SET expires_at=%s WHERE user_id=%s', (expiry, user))
    free_key = 'free:' + datetime(2026, 10, 25, 2).isoformat(timespec='microseconds')
    query('INSERT INTO user_quota_periods (user_id,period,plan_code,limit_seconds,used_seconds) '
          'VALUES (%s,%s,%s,%s,%s)', (user, free_key, 'free', 1800, 600))
    before = membership.summary(user)
    assert before['ends_with_membership'] and before['period_end'] == membership.iso(expiry)
    assert before['limit_seconds'] == 36000
    monkeypatch.setattr(account_store, 'utcnow', lambda: expiry)
    after = membership.summary(user)
    assert after['plan'] == 'free' and after['available_seconds'] == 1200
    assert after['resets_at'] == membership.iso(datetime(2026, 11, 25, 2))


def test_old_free_hold_is_settled_in_its_original_cycle_after_pro_opening(client, monkeypatch):
    user = uid(client)
    pending = hold(user, 100)
    membership.finalize(user, pending, 'unknown')
    membership.grant('alice@example.com', 'monthly')
    summary = membership.summary(user)
    assert summary['limit_seconds'] == 36000
    assert summary['pending_previous_seconds'] == 100
    assert summary['available_seconds'] == 35900
    membership.finalize(user, pending, 'settled')
    assert membership.summary(user)['available_seconds'] == 36000
    assert membership.summary(user)['used_seconds'] == 0
    paid = hold(user, 36000)
    with pytest.raises(TranscriptionError, match='不足'):
        hold(user, 1)  # There is no additional 30-minute free balance to spend.
    membership.finalize(user, paid, 'released')
    assert membership.summary(user)['available_seconds'] == 36000


def test_schema_widening_retains_legacy_holds_and_is_idempotent(client):
    user = uid(client)
    for table in ('user_quota_periods', 'quota_reservations'):
        query(f'ALTER TABLE {table} MODIFY COLUMN period CHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL')
    query('INSERT INTO user_quota_periods (user_id,period,plan_code,limit_seconds,reserved_seconds) '
          'VALUES (%s,%s,%s,%s,%s)', (user, '2026-11', 'free', 1800, 100))
    job = job_id()
    query('INSERT INTO quota_reservations (job_id,user_id,period,seconds,state,fingerprint,updated_at) '
          'VALUES (%s,%s,%s,%s,%s,%s,%s)', (job, user, '2026-11', 100, 'unknown', job.ljust(64, '0'), account_store.utcnow()))
    REAL_INIT_SCHEMA()
    REAL_INIT_SCHEMA()
    for table in ('user_quota_periods', 'quota_reservations'):
        assert query(f"SHOW COLUMNS FROM {table} LIKE 'period'")[0]['Type'] == 'varchar(40)'
    assert membership.summary(user)['pending_previous_seconds'] == 100
    membership.finalize(user, job, 'settled')
    assert query('SELECT used_seconds,reserved_seconds FROM user_quota_periods WHERE user_id=%s AND period=%s',
                 (user, '2026-11'))[0] == dict(used_seconds=100, reserved_seconds=0)
    assert membership.summary(user)['available_seconds'] == 1800


def test_guest_needs_login_for_subtitles_and_asr_but_member_subtitles_are_free(client, monkeypatch):
    monkeypatch.setattr(main, 'read_subtitles', lambda *a: ({'title': '平台字幕'}, SAMPLE, {'source': 'platform_subtitle'}))
    assert client.post('/api/transcript', json={'url': 'https://example.com/1'}).status_code == 403
    assert client.post('/api/transcriptions', json={'url': 'https://example.com/1', 'allow_asr': True}).status_code == 403
    assert client.post('/api/transcriptions', json={'url': 'https://example.com/1', 'allow_asr': False}).status_code == 403
    user = uid(client)
    for _ in range(2):
        assert client.post('/api/transcript', json={'url': 'https://example.com/1'}).status_code == 200
    history = client.get('/api/account/history').json()
    assert history['total'] == 1
    assert history['items'][0]['payload']['result']['source'] == 'platform_subtitle'
    assert membership.summary(user)['used_seconds'] == membership.summary(user)['reserved_seconds'] == 0


def test_asr_quota_history_restart_isolation_and_exports(client, cloud):
    user = uid(client)
    request = {'url': 'https://example.com/video/1', 'allow_asr': True}
    job = client.post('/api/transcriptions', json=request).json()
    result = wait(client, job['id'])
    assert result['status'] == 'done', result
    assert membership.summary(user)['used_seconds'] == 3  # input audio, not provider's two metered seconds
    assert cloud['submit'] == 1
    history = client.get('/api/account/history').json()
    assert history['total'] == 1 and history['items'][0]['quota_state'] == 'settled'
    with TestClient(main.app) as other:
        assert login(other).status_code == 200
        assert other.get('/api/transcriptions/' + job['id']).status_code == 200
        assert other.get('/api/account/history').json()['total'] == 1
        other.post('/api/auth/logout')
        register(other, 'bob_01')
        assert other.get('/api/account/history/' + job['id']).status_code == 404
        assert other.get('/api/account/history/' + job['id'] + '/file').status_code == 404
        assert other.get('/api/transcriptions/' + job['id']).status_code == 404
    # Drop in-memory jobs/files: durable history, polling and exports must still work without ASR.
    main.transcription_manager.jobs.clear()
    main.transcription_manager.keys.clear()
    import shutil
    shutil.rmtree(config.ASR_DIR / 'results')
    assert client.post('/api/transcriptions', json=request).json()['id'] == job['id']
    assert cloud['submit'] == 1
    for path in ('/api/transcriptions/', '/api/account/history/'):
        exported = client.get(path + job['id'] + '/file?format=srt')
        assert exported.status_code == 200 and '你好' in exported.text
        assert 'no-store' in exported.headers['cache-control']
    assert client.get('/api/account/history?search=Hello').json()['total'] == 1
    assert client.get('/api/account/history?status=active').json()['total'] == 0
    assert client.delete('/api/account/history/' + job['id']).status_code == 200
    assert client.get('/api/account/history').json()['total'] == 0
    assert membership.summary(user)['used_seconds'] == 3


@pytest.mark.parametrize('kind', ['quota', 'budget', 'failure', 'unknown'])
def test_no_charges_on_known_failures_and_hold_unknown(client, cloud, monkeypatch, kind):
    user = uid(client)
    if kind == 'quota':
        hold(user, 1800)
    elif kind == 'budget':
        monkeypatch.setattr(config, 'ASR_DAILY_BUDGET', '0')
    else:
        class Provider:
            def submit(self, url):
                cloud['submit'] += 1
                if kind == 'unknown':
                    raise TranscriptionError('CLOUD_NETWORK', '中断')
                return 'failed'
            def query(self, task):
                return Recognition('FAILED', [], 1)
        monkeypatch.setattr(asr, 'get_provider', Provider)
    job = client.post('/api/transcriptions', json={'url': 'https://example.com/video/1', 'allow_asr': True}).json()
    result = wait(client, job['id'])
    assert result['status'] == 'error', result
    summary = membership.summary(user)
    assert summary['used_seconds'] == 0
    assert summary['reserved_seconds'] == (1800 if kind == 'quota' else 3 if kind == 'unknown' else 0)
    if kind in ('quota', 'budget'):
        assert cloud['submit'] == 0


def test_history_expiration_and_orphan_recovery(client):
    from app.transcriptions import Transcription
    user = uid(client)
    job = Transcription(job_id(), f'user:{user}', 'c' * 64, 'https://example.com/1', None, True)
    membership.create_record(job)
    hold_id = job.id
    membership.reserve(user, hold_id, 20, job.key)
    membership.recover({}, set())
    assert membership.summary(user)['reserved_seconds'] == 0
    assert membership.record(user, job_id=job.id)['payload']['error_code'] == 'INTERRUPTED'
    query('UPDATE transcription_records SET expires_at=%s WHERE id=%s', (account_store.utcnow() - timedelta(seconds=1), job.id))
    assert client.get('/api/account/history/' + job.id).status_code == 404
    assert client.get('/api/account/history').json()['total'] == 0
    membership.cleanup()
    assert not query('SELECT id FROM transcription_records WHERE id=%s', (job.id,))
    assert query('SELECT state FROM quota_reservations WHERE job_id=%s', (job.id,))[0]['state'] == 'released'


def test_db_unavailable_prevents_asr_reservation(client, cloud, monkeypatch):
    user = uid(client)
    # Failure before any cloud request must never bypass user accounting.
    monkeypatch.setattr(config, 'MYSQL_PORT', 1)
    with pytest.raises(AccountError):
        hold(user, 3)
    assert cloud['submit'] == 0


def test_complete_failure_rolls_back_user_charge_and_recovers(client, cloud, monkeypatch):
    user = uid(client)
    real = membership.complete
    failed = []
    def fail_once(job, payload, state):
        if payload['status'] == 'done' and not failed:
            failed.append(True)
            raise AccountError('DB_UNAVAILABLE', '模拟提交失败', 503)
        return real(job, payload, state)
    monkeypatch.setattr(membership, 'complete', fail_once)
    job = client.post('/api/transcriptions', json={'url': 'https://example.com/video/1', 'allow_asr': True}).json()
    result = wait(client, job['id'])
    assert result['error_code'] == 'SUBMISSION_UNCERTAIN'
    assert membership.summary(user)['reserved_seconds'] == 3
    main.transcription_manager.reconcile()
    membership.recover(main.transcription_manager.ledger.entries(), set())
    recovered = client.get('/api/transcriptions/' + job['id']).json()
    assert recovered['status'] == 'done' and recovered['result']
    assert membership.summary(user)['used_seconds'] == 3
    assert membership.summary(user)['reserved_seconds'] == 0
    assert cloud['submit'] == 1


def test_batch_and_short_url_alias_share_user_charge(client, cloud):
    user = uid(client)
    batch = client.post('/api/batch-transcriptions', json={'urls': ['https://example.com/video/1', 'https://short.example/alias'], 'allow_asr': True}).json()
    for _ in range(400):
        state = client.get('/api/batch-transcriptions/' + batch['id']).json()
        if state['status'] in ('done', 'error'):
            break
        import time
        time.sleep(.01)
    assert state['succeeded'] == 2, state
    assert cloud['submit'] == 1
    assert membership.summary(user)['used_seconds'] == 3
    assert client.get('/api/account/history').json()['total'] == 1
    main.transcription_manager.jobs.clear()
    main.transcription_manager.keys.clear()
    alias = client.post('/api/transcriptions', json={'url': 'https://short.example/alias', 'allow_asr': True}).json()
    assert wait(client, alias['id'])['status'] == 'done'
    assert cloud['submit'] == 1


def test_active_history_and_duplicate_alias_while_running(client, cloud, monkeypatch):
    user = uid(client)
    gate = threading.Event()
    entered = threading.Event()
    class Provider:
        def submit(self, url):
            cloud['submit'] += 1
            entered.set()
            assert gate.wait(5)
            return 'slow'
        def query(self, task):
            return Recognition('SUCCEEDED', SAMPLE, 2)
    monkeypatch.setattr(asr, 'get_provider', Provider)
    original = client.post('/api/transcriptions', json={'url': 'https://example.com/video/1', 'allow_asr': True}).json()
    try:
        assert entered.wait(3)
        assert client.get('/api/account/history?status=active').json()['total'] == 1
        assert membership.summary(user)['reserved_seconds'] == 3
        alias = client.post('/api/transcriptions', json={'url': 'https://short.example/alias', 'allow_asr': True}).json()
    finally:
        gate.set()
    assert wait(client, original['id'])['status'] == 'done'
    assert wait(client, alias['id'])['status'] == 'done'
    assert cloud['submit'] == 1
    assert membership.summary(user)['used_seconds'] == 3


def test_partial_direct_recognition_releases_user_quota_but_keeps_provider_cost(client, cloud, monkeypatch):
    user = uid(client)
    monkeypatch.setattr(config, 'ASR_PROVIDER', 'fun-asr-flash')
    monkeypatch.setattr(config, 'ASR_MODEL', 'fun-asr-flash-2026-06-15')
    monkeypatch.setattr(transcriptions, 'prepare_segments', lambda path, duration: [(path, 1.1, 0), (path, 1.9, 1100)])
    class Provider:
        def recognize(self, audio, submitted, stop, *, duration, offset_ms):
            submitted(str(offset_ms))
            if offset_ms:
                raise TranscriptionError('CLOUD_REJECTED', '拒绝第二段')
            return Recognition('SUCCEEDED', SAMPLE, 1.1)
    monkeypatch.setattr(asr, 'get_provider', Provider)
    job = client.post('/api/transcriptions', json={'url': 'https://example.com/video/1', 'allow_asr': True}).json()
    assert wait(client, job['id'])['error_code'] == 'PARTIAL_RECOGNITION'
    assert membership.summary(user)['available_seconds'] == 1800
    assert main.transcription_manager.ledger.entries()[job['id']]['state'] == 'settled'


def test_complete_sql_failure_is_atomic(client, monkeypatch):
    from app.transcriptions import Transcription
    user = uid(client)
    job = Transcription(job_id(), f'user:{user}', 'b' * 64, 'https://example.com/1', None, True)
    membership.create_record(job)
    membership.reserve(user, job.id, 60, job.key)
    # Invalid payload deliberately fails AFTER quota updates, inside the same DB transaction.
    with pytest.raises(KeyError):
        membership.complete(job, {'status': 'done'}, 'settled')
    assert membership.summary(user)['reserved_seconds'] == 60
    assert membership.summary(user)['used_seconds'] == 0
    assert not query("SELECT * FROM quota_events WHERE job_id=%s AND action='settled'", (job.id,))
