"""Real isolated MySQL; platform and speech calls are ALWAYS simulated."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import account_auth, account_store, asr, config, main, membership, open_api_auth, open_api_store, transcriptions
from app.errors import NoSubtitles, TranscriptionError
from .test_accounts import db, register, query, PASSWORD
from .test_transcriptions import cloud, SAMPLE

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason='MYSQL_TEST_DATABASE not configured')
VIDEO = 'https://www.douyin.com/video/7420000000000000000'
MEDIA = {'url': VIDEO, 'title': '开放接口测试', 'duration': 3, 'platform': 'Douyin',
         'direct': {'url': 'https://cdn.example/video.mp4'}, 'thumbnail': 'https://cdn.example/cover.jpg'}


@pytest.fixture(autouse=True)
def setup(db, monkeypatch):
    query('DELETE FROM membership_plans')
    membership.seed()
    monkeypatch.setattr(open_api_auth, '_public_dns', lambda host: None)


def member(client, name='developer'):
    response = register(client, name)
    assert response.status_code == 200, response.text
    uid = response.json()['user']['id']
    membership.grant(name + '@example.com', 'monthly')
    return uid


def key(client, name='测试应用'):
    response = client.post('/api/account/api-keys', json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()


def headers(token, idem='test-1'):
    return {'Authorization': 'Bearer ' + token, 'Idempotency-Key': idem}


def submit(client, token, idem='test-1', **extra):
    return client.post('/api/open/v1/transcriptions', headers=headers(token, idem), json={'url': VIDEO, **extra})


def wait(client, token, task_id):
    for _ in range(50):
        response = client.get('/api/open/v1/transcriptions/' + task_id, headers=headers(token))
        assert response.status_code == 200, response.text
        data = response.json()['data']
        if data['status'] not in ('queued', 'running'):
            return data
        time.sleep(.02)
    raise AssertionError('task did not finish')


def native(monkeypatch):
    monkeypatch.setattr(transcriptions, 'read_subtitles', lambda *a: (MEDIA, SAMPLE, {'source': 'platform_subtitle', 'language': 'zh'}))
    monkeypatch.setattr(asr, 'get_provider', lambda: pytest.fail('native subtitles must not call ASR'))


def test_keys_auth_lifecycle_and_digest_only(client):
    uid = member(client)
    created = key(client)
    token = created['token']
    assert token.startswith('fv_live_')
    rows = query('SELECT * FROM open_api_keys WHERE user_id=%s', (uid,))
    assert rows[0]['token_hash'] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(rows)
    listing = client.get('/api/account/api-keys')
    assert token not in listing.text and 'token_hash' not in listing.text
    assert listing.headers['cache-control'] == 'no-store'
    assert client.get('/api/open/v1/quota').status_code == 401  # website cookie is not a key
    assert client.get('/api/open/v1/quota', headers=headers(token)).status_code == 200
    outsider = TestClient(main.app)
    member(outsider, 'other')
    assert outsider.delete('/api/account/api-keys/' + created['key']['id']).status_code == 404
    assert client.delete('/api/account/api-keys/' + created['key']['id']).status_code == 200
    assert client.get('/api/open/v1/quota', headers=headers(token)).status_code == 401


def test_free_cannot_create_keys_limit_and_origin(client):
    register(client)
    assert client.post('/api/account/api-keys', json={'name': 'free'}).status_code == 403
    membership.grant('alice@example.com', 'monthly')
    assert client.post('/api/account/api-keys', headers={'Origin': 'https://evil.example'}, json={'name': 'x'}).status_code == 403
    for i in range(3):
        key(client, str(i))
    assert client.post('/api/account/api-keys', json={'name': 'fourth'}).json()['code'] == 'API_KEY_LIMIT'
    assert client.post('/api/account/api-keys', json={'name': '\n\t'}).status_code == 422


def test_native_media_exports_idempotency_and_history_isolation(client, monkeypatch):
    uid = member(client)
    token = key(client)['token']
    native(monkeypatch)
    response = submit(client, token)
    assert response.status_code == 202, response.text
    tid = response.json()['data']['task_id']
    data = wait(client, token, tid)
    assert data['status'] == 'succeeded' and data['result']['source'] == 'platform_subtitle'
    assert data['video_url'] == MEDIA['direct']['url'] and data['cover_url'] == MEDIA['thumbnail']
    assert data['source_url'] == VIDEO and '可能过期' in data['media_notice']
    assert membership.summary(uid)['used_seconds'] == 0
    assert submit(client, token).json()['data']['task_id'] == tid
    assert submit(client, token, allow_asr=True).status_code == 409
    # Same account can rotate keys and still query its API tasks.
    other_token = key(client)['token']
    assert client.get('/api/open/v1/transcriptions/' + tid, headers=headers(other_token)).status_code == 200
    internal = query('SELECT transcription_id FROM open_api_requests WHERE id=%s', (tid,))[0]['transcription_id']
    assert client.get('/api/open/v1/transcriptions/' + internal, headers=headers(token)).status_code == 404
    for fmt in ('txt', 'srt'):
        export = client.get(f'/api/open/v1/transcriptions/{tid}/file?format={fmt}', headers=headers(token))
        assert export.status_code == 200 and '你好' in export.text
        assert export.headers['cache-control'] == 'no-store' and "filename*=UTF-8''" in export.headers['content-disposition']
    # Persistent result restores all media metadata without network or ASR.
    main.transcription_manager.jobs.clear()
    main.transcription_manager.keys.clear()
    assert wait(client, token, tid)['video_url'] == MEDIA['direct']['url']
    outsider = TestClient(main.app)
    member(outsider, 'outsider')
    foreign = key(outsider)['token']
    assert outsider.get('/api/open/v1/transcriptions/' + tid, headers=headers(foreign)).status_code == 404


def test_paid_asr_settles_once_and_unknown_holds(client, cloud, monkeypatch):
    uid = member(client)
    token = key(client)['token']
    response = submit(client, token, allow_asr=True)
    tid = response.json()['data']['task_id']
    assert wait(client, token, tid)['status'] == 'succeeded'
    assert cloud['submit'] == 1 and membership.summary(uid)['used_seconds'] == 3
    assert submit(client, token, allow_asr=True).json()['data']['task_id'] == tid
    # New key, same work: backend deduplication still prevents a second paid submit.
    other = submit(client, token, 'new-key', allow_asr=True).json()['data']['task_id']
    assert wait(client, token, other)['status'] == 'succeeded' and cloud['submit'] == 1


def test_unknown_no_automatic_resubmit(client, cloud, monkeypatch):
    uid = member(client)
    token = key(client)['token']
    class Provider:
        def submit(self, url):
            cloud['submit'] += 1
            raise TranscriptionError('CLOUD_PENDING', 'submit result unknown')
    monkeypatch.setattr(asr, 'get_provider', Provider)
    tid = submit(client, token, allow_asr=True).json()['data']['task_id']
    data = wait(client, token, tid)
    assert data['status'] == 'uncertain' and not data['error']['retryable']
    assert membership.summary(uid)['reserved_seconds'] == 3
    tid2 = submit(client, token, 'new-key', allow_asr=True).json()['data']['task_id']
    assert wait(client, token, tid2)['status'] == 'uncertain' and cloud['submit'] == 1
    assert client.get(f'/api/open/v1/transcriptions/{tid}/file', headers=headers(token)).status_code == 409


def test_no_implicit_asr_and_quota_failure(client, cloud):
    uid = member(client)
    token = key(client)['token']
    tid = submit(client, token).json()['data']['task_id']
    assert wait(client, token, tid)['error']['code'] == 'ASR_REQUIRED' and cloud['submit'] == 0
    query("UPDATE membership_plans SET monthly_seconds=1 WHERE code='monthly'")
    tid = submit(client, token, 'paid', allow_asr=True).json()['data']['task_id']
    assert wait(client, token, tid)['error']['code'] == 'QUOTA_EXCEEDED'
    assert cloud['submit'] == 0 and membership.summary(uid)['used_seconds'] == 0


def test_membership_expiry_keeps_existing_queries(client, monkeypatch):
    uid = member(client)
    token = key(client)['token']
    native(monkeypatch)
    tid = submit(client, token).json()['data']['task_id']
    wait(client, token, tid)
    query('UPDATE user_memberships SET expires_at=%s WHERE user_id=%s', (account_store.utcnow() - timedelta(seconds=1), uid))
    assert submit(client, token, 'new').status_code == 403
    assert client.post('/api/account/api-keys', json={'name': 'new'}).status_code == 403
    assert submit(client, token).json()['data']['task_id'] == tid
    assert client.get('/api/open/v1/transcriptions/' + tid, headers=headers(token)).status_code == 200


def test_change_password_revokes_keys(client):
    uid = member(client)
    token = key(client)['token']
    res = client.post('/api/account/password', json={'old_password': PASSWORD, 'new_password': 'updated password 2026'})
    assert res.status_code == 200, res.text
    assert query('SELECT revoked_at FROM open_api_keys WHERE user_id=%s', (uid,))[0]['revoked_at']
    assert client.get('/api/open/v1/quota', headers=headers(token)).status_code == 401


def test_concurrent_idempotency_and_account_capacity(client, monkeypatch):
    uid = member(client)
    token = key(client)['token']
    monkeypatch.setattr(main.transcription_manager.pool, 'submit', lambda *a: None)
    def send(_):
        return submit(TestClient(main.app), token)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(send, range(5)))
    assert all(r.status_code == 202 for r in results), [r.text for r in results]
    assert len({r.json()['data']['task_id'] for r in results}) == 1
    assert len(query('SELECT id FROM open_api_requests WHERE user_id=%s', (uid,))) == 1
    second = client.post('/api/open/v1/transcriptions', headers=headers(token, 'second'),
                         json={'url': 'https://www.douyin.com/video/7420000000000000001'})
    assert second.status_code == 202
    third = submit(client, key(client)['token'], 'third')
    assert third.status_code == 429 and third.headers['retry-after'] == '60'
    assert query('SELECT COUNT(*) AS n FROM transcription_records WHERE user_id=%s', (uid,))[0]['n'] == 2


def test_recovery_admission_windows_never_enqueue(client, monkeypatch):
    uid = member(client)
    created = key(client)
    principal = {'user_id': uid, 'key_id': created['key']['id']}
    row, fresh = open_api_store.admit(principal, 'crash-before-record', 'a' * 64)
    assert fresh
    open_api_store.recover()
    saved = open_api_store.lookup(uid, row['id'])
    assert saved['failure']['code'] == 'INTERRUPTED'
    monkeypatch.setattr(main.transcription_manager.pool, 'submit', lambda *a: None)
    row2, _ = open_api_store.admit(principal, 'crash-after-record', 'b' * 64)
    main.transcription_manager.submit(f'user:{uid}', VIDEO, job_id=row2['transcription_id'])
    open_api_store.recover()
    assert open_api_store.lookup(uid, row2['id'])['state'] == 'submitted'
    assert len(main.transcription_manager.jobs) == 1


def test_validation_errors_contract_and_schema(client):
    member(client)
    token = key(client)['token']
    for body in ({'url': VIDEO, 'owner': 'user:99'}, {'url': VIDEO, 'allow_asr': 'true'}, {'url': VIDEO, 'lang': '\n'}):
        response = client.post('/api/open/v1/transcriptions', json=body, headers=headers(token))
        assert response.status_code == 422
        assert set(response.json()) == {'request_id', 'error'}
        assert response.headers['x-request-id'] == response.json()['request_id']
    assert client.post('/api/open/v1/transcriptions', json={'url': VIDEO}, headers={'Authorization': 'Bearer ' + token}).status_code == 422
    response = client.post('/api/open/v1/transcriptions', headers=headers(token, 'unsafe'), json={'url': 'http://127.0.0.1/private'})
    assert response.status_code == 422 and response.json()['error']['code'] == 'UNSUPPORTED_URL'
    schema = client.get('/api/openapi.json').json()
    assert set(schema['paths']) == {'/api/open/v1/transcriptions', '/api/open/v1/transcriptions/{task_id}', '/api/open/v1/transcriptions/{task_id}/file', '/api/open/v1/quota'}
    assert schema['paths']['/api/open/v1/transcriptions']['post']['security'] == [{'DeveloperKey': []}]
    assert 'video_url' in schema['components']['schemas']['TaskData']['properties']
    assert schema['paths']['/api/open/v1/transcriptions']['post']['parameters'][0]['name'] == 'Idempotency-Key'


def test_reset_revokes_keys_and_credential_snapshot_blocks_old_key(client):
    from app import password_reset
    uid = member(client)
    token = key(client)['token']
    reset_token = 'x' * 43
    password_hash = account_store.get_password_hash(uid)
    query('INSERT INTO password_resets (user_id,token_hash,credential_hash,created_at,expires_at) VALUES (%s,%s,%s,%s,%s)',
          (uid, account_auth.token_hash(reset_token), hashlib.sha256(password_hash.encode()).hexdigest(), account_store.utcnow(), account_store.utcnow() + timedelta(minutes=30)))
    password_reset.reset(reset_token, 'new reset password 2026')
    assert query('SELECT revoked_at FROM open_api_keys WHERE user_id=%s', (uid,))[0]['revoked_at']
    assert client.get('/api/open/v1/quota', headers=headers(token)).status_code == 401
    # Even a manually cleared revoke flag cannot restore a credential bound to the old password.
    query('UPDATE open_api_keys SET revoked_at=NULL WHERE user_id=%s', (uid,))
    assert client.get('/api/open/v1/quota', headers=headers(token)).status_code == 401


def test_alias_active_capacity_and_db_restoration(client, monkeypatch):
    from app.transcriptions import Transcription
    uid = member(client)
    token = key(client)['token']
    owner = f'user:{uid}'
    target = Transcription(uuid.uuid4().hex, owner, 'a' * 64, VIDEO, None, True, status='running')
    membership.create_record(target)
    alias = Transcription(uuid.uuid4().hex, owner, 'b' * 64, VIDEO, None, True, status='done', reuse_id=target.id)
    membership.create_record(alias)
    membership.save_alias(alias, target.id)
    principal = open_api_store.authenticate(hashlib.sha256(token.encode()).hexdigest())
    row, _ = open_api_store.admit(principal, 'alias-grant', 'c' * 64)
    open_api_store.bind(row, alias)
    # The effective target is active even though its alias record says done.
    row2, _ = open_api_store.admit(principal, 'second', 'd' * 64)
    with pytest.raises(Exception, match='最多同时'):
        open_api_store.admit(principal, 'third', 'e' * 64)
    main.transcription_manager.jobs[alias.id] = alias
    assert main.transcription_manager.get(alias.id, owner).id == target.id  # target only exists in SQL


def test_scheduler_rejection_frees_capacity_and_idem_is_stable(client, monkeypatch):
    uid = member(client)
    token = key(client)['token']
    def stopping(*a):
        raise RuntimeError('executor stopping')
    monkeypatch.setattr(main.transcription_manager.pool, 'submit', stopping)
    response = submit(client, token)
    assert response.status_code == 503
    row = query('SELECT * FROM open_api_requests WHERE user_id=%s', (uid,))[0]
    repeated = submit(client, token)
    assert repeated.status_code == 202 and repeated.json()['data']['status'] == 'failed'
    assert wait(client, token, row['id'])['error']['code'] == 'RECOVERING'
    assert membership.summary(uid)['used_seconds'] == 0


def test_rate_limit_shared_across_keys_and_error_response_sanitized(client, monkeypatch):
    member(client)
    first, second = key(client)['token'], key(client)['token']
    for _ in range(60):
        assert client.get('/api/open/v1/quota', headers=headers(first)).status_code == 200
    response = client.get('/api/open/v1/quota', headers=headers(second))
    assert response.status_code == 429 and response.headers['retry-after'] == '60'
    assert response.json()['error']['retryable']
    account_auth.reset_limits()
    def broken(*a, **k):
        raise RuntimeError('sensitive-upstream-key-must-not-leak')
    monkeypatch.setattr(main.transcription_manager, 'submit', broken)
    response = submit(client, first)
    assert response.status_code == 503 and 'sensitive-upstream' not in response.text
    response = submit(client, first)
    assert response.json()['data']['error']['code'] == 'ADMISSION_INTERRUPTED'


def test_database_outage_during_admission_recovers_without_restart(client, monkeypatch):
    from app.errors import AccountError
    uid = member(client)
    token = key(client)['token']
    with monkeypatch.context() as patch:
        def network_failure(*a):
            raise RuntimeError('connection interrupted before enqueue')
        def database_failure(*a):
            raise AccountError('DB_UNAVAILABLE', '数据库暂不可用', 503)
        patch.setattr(open_api_auth, 'video_url', network_failure)
        patch.setattr(open_api_store, 'fail', database_failure)
        assert submit(client, token).status_code == 503
    row = query('SELECT id,state FROM open_api_requests WHERE user_id=%s', (uid,))[0]
    assert row['state'] == 'submitting'
    data = wait(client, token, row['id'])
    assert data['status'] == 'failed' and data['error']['code'] == 'INTERRUPTED'
    monkeypatch.setattr(main.transcription_manager.pool, 'submit', lambda *a: None)
    assert submit(client, token, 'next-job').status_code == 202
