"""Lifetime anonymous AI trial: real isolated MySQL, simulated media/AI/ASR only."""
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
import json
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import account_store, ai_learning, asr, config, downloader, guest, main, membership, transcriptions
from app.errors import TranscriptionError, VideoError
from .test_accounts import db, query, register
from .test_transcriptions import cloud, SAMPLE

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason='MYSQL_TEST_DATABASE not configured')
BASE = '/api/guest/ai-summary'
VIDEO = 'https://www.douyin.com/video/7420000000000000000'
SECOND = 'https://www.douyin.com/video/7420000000000000001'
INFO = dict(url=VIDEO, title='游客体验测试', duration=120, platform='Douyin', qualities=[],
            thumbnail='https://cdn.example/cover.jpg', direct={'url': 'https://cdn.example/video.mp4'})
SUMMARY = '## 核心结论\n\n[00:00] 这是游客可以阅读的总结。'


@pytest.fixture(autouse=True)
def fresh(db, monkeypatch):
    query('DELETE FROM guest_ai_subjects')
    query('DELETE FROM guest_ai_trials')
    query('DELETE FROM guest_links')
    membership.seed()
    monkeypatch.setattr(config, 'DEEPSEEK_API_KEY', 'offline-test-key')
    monkeypatch.setattr(downloader, 'parse', lambda url: {**INFO, 'url': url})


@pytest.fixture
def native(monkeypatch):
    calls = {'summary': 0, 'asr': 0}
    monkeypatch.setattr(transcriptions, 'read_subtitles',
                        lambda url, *a, **k: ({**INFO, 'url': url}, SAMPLE,
                                             {'source': 'platform_subtitle', 'language': 'zh'}))

    def summarize(*a, **k):
        calls['summary'] += 1
        yield 'delta', SUMMARY
    monkeypatch.setattr(ai_learning, 'summarize_events', summarize)

    def no_asr(*a, **k):
        calls['asr'] += 1
        raise AssertionError('Native subtitles must not invoke paid speech recognition')
    monkeypatch.setattr(asr, 'get_provider', no_asr)
    return calls


def submit(client, url=VIDEO):
    return client.post(BASE, json={'url': url})


def accepted(response):
    assert response.status_code in (200, 202), response.text
    result = response.json()
    assert result.get('id'), result
    return result


def wait(client, trial_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(BASE + '/' + trial_id)
        assert response.status_code == 200, response.text
        data = response.json()
        if data['status'] in ('done', 'error', 'uncertain'):
            return data
        time.sleep(.02)
    raise AssertionError('Guest AI trial did not finish')


def guest_client(ip='203.0.113.40'):
    # Do not enter another lifespan: the fixture owns the one shared manager.
    return TestClient(main.app, client=(ip, 5000))


def test_native_success_is_lifetime_and_repeat_result_is_free(client, native):
    client.cookies.clear()
    initial = client.get(BASE)
    assert initial.status_code == 200
    assert initial.json()['available'] is True and initial.json()['max_seconds'] == 180
    assert 'no-store' in initial.headers['cache-control']
    trial = accepted(submit(client))
    result = wait(client, trial['id'])
    assert result['status'] == 'done' and result['summary'] == SUMMARY
    assert result['info']['url'] == VIDEO
    assert result['transcript']['source'] == 'platform_subtitle'
    assert native == {'summary': 1, 'asr': 0}
    status = client.get(BASE).json()
    assert status['available'] is False
    assert status['task']['id'] == trial['id']
    repeated = accepted(submit(client))
    assert repeated['id'] == trial['id'] and repeated['summary'] == SUMMARY
    assert native['summary'] == 1
    blocked = submit(client, SECOND)
    assert blocked.status_code == 403 and blocked.json()['code'] == 'GUEST_AI_LIMIT'
    assert query('SELECT COUNT(*) AS n FROM guest_links')[0]['n'] == 0


def test_same_ip_new_cookie_cannot_retry_or_read_another_visitor_result(client, native):
    client.cookies.clear()
    trial = accepted(submit(client))
    assert wait(client, trial['id'])['status'] == 'done'
    other = TestClient(main.app)  # same default client IP, no original browser cookie
    state = other.get(BASE)
    assert state.status_code == 200 and state.json()['available'] is False
    assert state.json().get('task') is None
    assert other.get(BASE + '/' + trial['id']).status_code == 404
    denied = submit(other, SECOND)
    assert denied.status_code == 403 and denied.json()['code'] == 'GUEST_AI_LIMIT'
    client.cookies.clear()
    assert submit(client, SECOND).status_code == 403
    assert native['summary'] == 1


def test_same_cookie_on_new_ip_keeps_its_allowance(client, native):
    client.cookies.clear()
    trial = accepted(submit(client))
    wait(client, trial['id'])
    moved = guest_client('203.0.113.41')
    moved.cookies.set(guest.COOKIE, client.cookies.get(guest.COOKIE))
    assert moved.get(BASE + '/' + trial['id']).status_code == 200
    assert submit(moved, SECOND).status_code == 403
    independent = guest_client('203.0.113.42')
    trial2 = accepted(submit(independent, SECOND))
    assert wait(independent, trial2['id'])['status'] == 'done'
    assert native['summary'] == 2


def test_download_allowance_and_trial_do_not_consume_each_other(client, native):
    client.cookies.clear()
    for url in (VIDEO, SECOND):
        assert client.post('/api/parse', json={'url': url}).status_code == 200
    assert client.post('/api/parse', json={'url': SECOND + '9'}).status_code == 403
    trial = accepted(submit(client))
    assert wait(client, trial['id'])['status'] == 'done'
    assert query('SELECT COUNT(*) AS n FROM guest_links WHERE subject LIKE %s', ('c:%',))[0]['n'] == 2


def test_failed_empty_summary_releases_the_one_trial(client, native, monkeypatch):
    client.cookies.clear()
    monkeypatch.setattr(ai_learning, 'summarize_events', lambda *a, **k: iter(()))
    failed = accepted(submit(client))
    result = wait(client, failed['id'])
    assert result['status'] == 'error' and not result['summary']
    assert client.get(BASE).json()['available'] is True
    monkeypatch.setattr(ai_learning, 'summarize_events', lambda *a, **k: iter([('delta', SUMMARY)]))
    success = accepted(submit(client, SECOND))
    assert wait(client, success['id'])['status'] == 'done'


def test_partial_summary_is_saved_and_cannot_buy_another_trial(client, native, monkeypatch):
    client.cookies.clear()
    def partial(*a, **k):
        yield 'delta', '已经产生的有效总结'
        raise VideoError('模型连接中断')
    monkeypatch.setattr(ai_learning, 'summarize_events', partial)
    trial = accepted(submit(client))
    result = wait(client, trial['id'])
    assert '已经产生的有效总结' in result['summary']
    assert client.get(BASE).json()['available'] is False
    assert submit(client, SECOND).status_code == 403
    assert client.get(BASE + '/' + trial['id']).json()['summary'] == result['summary']


def test_parallel_submits_reserve_only_one_model_call(client, native, monkeypatch):
    client.cookies.clear()
    assert client.get(BASE).status_code == 200  # one shared, signed browser identity
    cookie = client.cookies.get(guest.COOKIE)
    entered, release = threading.Event(), threading.Event()
    def slow(*a, **k):
        native['summary'] += 1
        entered.set()
        assert release.wait(4)
        yield 'delta', SUMMARY
    monkeypatch.setattr(ai_learning, 'summarize_events', slow)
    def send(_):
        browser = TestClient(main.app)
        browser.cookies.set(guest.COOKIE, cookie)
        return submit(browser)
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(pool.map(send, range(5)))
        assert all(r.status_code in (200, 202) for r in responses), [r.text for r in responses]
        ids = {r.json()['id'] for r in responses}
        assert len(ids) == 1
        assert entered.wait(4)
        assert native['summary'] == 1
    finally:
        release.set()
    assert wait(client, ids.pop())['status'] == 'done'


@pytest.mark.parametrize('duration', [180.01, 181, 3600])
def test_metadata_over_three_minutes_is_rejected_before_recognition(client, native, monkeypatch, duration):
    client.cookies.clear()
    monkeypatch.setattr(downloader, 'parse', lambda url: {**INFO, 'url': url, 'duration': duration})
    response = submit(client)
    if response.status_code in (200, 202):
        result = wait(client, accepted(response)['id'])
        assert result['status'] == 'error' and result['error_code'] == 'GUEST_AI_TOO_LONG'
    else:
        assert response.status_code == 403 and response.json()['code'] == 'GUEST_AI_TOO_LONG'
    assert native == {'summary': 0, 'asr': 0}
    assert client.get(BASE).json()['available'] is True


def test_exactly_three_minutes_can_be_summarized(client, native, monkeypatch):
    client.cookies.clear()
    monkeypatch.setattr(downloader, 'parse', lambda url: {**INFO, 'url': url, 'duration': 180})
    trial = accepted(submit(client))
    assert wait(client, trial['id'])['status'] == 'done'


def test_guest_trial_does_not_unlock_other_protected_apis(client, native):
    client.cookies.clear()
    for path, body, expected_status in (
        ('/api/learn/summary', {'url': VIDEO}, 401),
        ('/api/learn/mindmap', {'url': VIDEO}, 401),
        ('/api/learn/chat', {'url': VIDEO, 'messages': [{'role': 'user', 'content': '解释一下'}]}, 401),
        ('/api/ai/summary', {'url': VIDEO}, 401),
        ('/api/ai/translate', {'url': VIDEO}, 401),
        ('/api/transcriptions', {'url': VIDEO, 'allow_asr': True}, 403),
        ('/api/transcript', {'url': VIDEO}, 403),
    ):
        assert client.post(path, json=body).status_code == expected_status, path
    trial = accepted(submit(client))
    wait(client, trial['id'])
    assert client.post('/api/learn/mindmap', json={'url': VIDEO}).status_code == 401
    assert client.post('/api/transcript', json={'url': VIDEO}).status_code == 403


def test_trial_never_creates_account_quota_or_login_debt(client, native):
    client.cookies.clear()
    trial = accepted(submit(client))
    wait(client, trial['id'])
    assert query('SELECT COUNT(*) AS n FROM quota_reservations')[0]['n'] == 0
    assert query('SELECT COUNT(*) AS n FROM transcription_records')[0]['n'] == 0
    registered = register(client, 'guest-trial-register')
    assert registered.status_code == 200, registered.text
    assert registered.json()['guest_claimed_seconds'] == 0
    uid = registered.json()['user']['id']
    assert membership.summary(uid)['used_seconds'] == 0


def test_rejects_origin_and_client_supplied_summary_or_transcript(client, native):
    client.cookies.clear()
    cross_site = client.post(BASE, json={'url': VIDEO}, headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'})
    assert cross_site.status_code == 403
    injection = client.post(BASE, json={'url': VIDEO, 'transcript': 'pretend this is the video', 'duration': 1})
    assert injection.status_code == 422
    assert native['summary'] == 0


def test_no_subtitles_trial_uses_asr_once_without_account_quota(client, cloud, monkeypatch):
    client.cookies.clear()
    calls = []
    def summarize(*a, **k):
        calls.append(k)
        yield 'delta', SUMMARY
    monkeypatch.setattr(ai_learning, 'summarize_events', summarize)
    trial = accepted(submit(client))
    result = wait(client, trial['id'])
    assert result['status'] == 'done' and result['transcript']['source'] == 'asr'
    assert cloud['submit'] == 1 and len(calls) == 1
    assert query('SELECT COUNT(*) AS n FROM quota_reservations')[0]['n'] == 0
    assert accepted(submit(client))['id'] == trial['id']
    assert cloud['submit'] == 1
    serialized = json.dumps(result)
    assert 'private.example' not in serialized and 'internal-cloud-task' not in serialized


def test_actual_audio_over_three_minutes_stops_before_paid_submit(client, cloud, monkeypatch):
    client.cookies.clear()
    def too_long_audio(url, directory, report):
        path = directory / 'input.mp3'
        path.write_bytes(b'offline fake audio')
        return path, 180.01
    monkeypatch.setattr(transcriptions, 'acquire_audio', too_long_audio)
    monkeypatch.setattr(ai_learning, 'summarize_events', lambda *a, **k: pytest.fail('Do not summarize overlong audio'))
    trial = accepted(submit(client))
    result = wait(client, trial['id'])
    assert result['status'] == 'error' and result['error_code'] == 'GUEST_AI_TOO_LONG'
    assert cloud['submit'] == 0
    assert client.get(BASE).json()['available'] is True


def test_asr_result_is_reused_after_model_failed_without_output(client, cloud, monkeypatch):
    client.cookies.clear()
    calls = []
    def summarize(*a, **k):
        calls.append(True)
        if len(calls) == 1:
            raise VideoError('第一次模型请求失败，没有输出')
        yield 'delta', SUMMARY
    monkeypatch.setattr(ai_learning, 'summarize_events', summarize)
    first = accepted(submit(client))
    failed = wait(client, first['id'])
    assert failed['status'] == 'error' and not failed['summary']
    assert cloud['submit'] == 1
    assert client.get(BASE).json()['available'] is True
    second = accepted(submit(client))
    done = wait(client, second['id'])
    assert done['status'] == 'done' and done['summary'] == SUMMARY
    assert cloud['submit'] == 1, 'A failed model request must not make the visitor pay for ASR twice'
    assert len(calls) == 2


def test_uncertain_asr_holds_trial_and_never_resends_audio(client, cloud, monkeypatch):
    client.cookies.clear()
    class Provider:
        def submit(self, url):
            cloud['submit'] += 1
            raise TranscriptionError('CLOUD_NETWORK', '云请求是否受理未知', True)
    monkeypatch.setattr(asr, 'get_provider', Provider)
    monkeypatch.setattr(ai_learning, 'summarize_events', lambda *a, **k: pytest.fail('Unknown ASR cannot be summarized'))
    trial = accepted(submit(client))
    result = wait(client, trial['id'])
    assert result['status'] == 'uncertain' and not result['retryable']
    assert not client.get(BASE).json()['available']
    assert accepted(submit(client))['id'] == trial['id']
    assert submit(client, SECOND).status_code == 403
    assert cloud['submit'] == 1


def queued_without_worker(client, monkeypatch):
    client.cookies.clear()
    monkeypatch.setattr(main.guest_ai_manager.pool, 'submit', lambda *a, **k: Future())
    return accepted(submit(client))


def test_restart_before_work_releases_unused_trial_without_provider_calls(client, native, monkeypatch):
    from app.guest_ai_trial import TrialManager
    trial = queued_without_worker(client, monkeypatch)
    replacement = TrialManager(lambda: main.transcription_manager)
    try:
        replacement.recover()
        row = query('SELECT state,payload FROM guest_ai_trials WHERE id=%s', (trial['id'],))[0]
        payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        assert row['state'] == 'error' and payload['error_code'] == 'INTERRUPTED'
        assert payload['retryable'] is True
        assert {r['state'] for r in query('SELECT state FROM guest_ai_subjects WHERE trial_id=%s', (trial['id'],))} == {'available'}
        assert native == {'summary': 0, 'asr': 0}
    finally:
        replacement.stop()
        replacement.pool.shutdown(wait=True, cancel_futures=True)


def test_restart_unknown_cloud_request_keeps_claim_and_never_enqueues(client, native, monkeypatch):
    from app.guest_ai_trial import TrialManager
    trial = queued_without_worker(client, monkeypatch)
    tid = uuid.uuid4().hex
    query('UPDATE guest_ai_trials SET transcription_id=%s WHERE id=%s', (tid, trial['id']))
    ledger = main.transcription_manager.ledger
    ledger.reserve(tid, 3, None)
    ledger.update(tid, state='submitting')
    replacement = TrialManager(lambda: main.transcription_manager)
    try:
        replacement.recover()
        row = query('SELECT state,payload FROM guest_ai_trials WHERE id=%s', (trial['id'],))[0]
        payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        assert row['state'] == 'uncertain' and payload['error_code'] == 'SUBMISSION_UNCERTAIN'
        assert not payload['retryable']
        assert {r['state'] for r in query('SELECT state FROM guest_ai_subjects WHERE trial_id=%s', (trial['id'],))} == {'uncertain'}
        assert submit(client, SECOND).status_code == 403
        assert native == {'summary': 0, 'asr': 0}
    finally:
        replacement.stop()
        replacement.pool.shutdown(wait=True, cancel_futures=True)


def test_restart_settled_speech_recovers_local_result_for_model_only_retry(client, native, monkeypatch):
    from app.guest_ai_trial import TrialManager
    from app.subtitles import to_srt
    trial = queued_without_worker(client, monkeypatch)
    tid = uuid.uuid4().hex
    query('UPDATE guest_ai_trials SET transcription_id=%s WHERE id=%s', (tid, trial['id']))
    ledger = main.transcription_manager.ledger
    ledger.reserve(tid, 3, None)
    ledger.settle(tid, 3)
    directory = config.ASR_DIR / 'results' / tid
    directory.mkdir(parents=True)
    (directory / 'transcript.srt').write_text(to_srt(SAMPLE), encoding='utf-8')
    replacement = TrialManager(lambda: main.transcription_manager)
    monkeypatch.setattr(main, 'guest_ai_manager', replacement)
    try:
        replacement.recover()
        row = query('SELECT state,payload FROM guest_ai_trials WHERE id=%s', (trial['id'],))[0]
        payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        assert row['state'] == 'error' and payload['transcript']['source'] == 'asr'
        assert payload['retryable'] and native['summary'] == 0
        resumed = accepted(submit(client))
        done = wait(client, resumed['id'])
        assert done['status'] == 'done' and done['transcript']['source'] == 'asr'
        assert native == {'summary': 1, 'asr': 0}
        assert len(ledger.entries()) == 1
    finally:
        replacement.stop()
        replacement.pool.shutdown(wait=True, cancel_futures=True)


def test_result_expiry_does_not_reset_lifetime_trial(client, native):
    client.cookies.clear()
    trial = accepted(submit(client))
    assert wait(client, trial['id'])['status'] == 'done'
    query('UPDATE guest_ai_trials SET expires_at=%s WHERE id=%s', (account_store.utcnow() - timedelta(seconds=1), trial['id']))
    state = client.get(BASE).json()
    assert not state['available'] and state['task'] is None
    assert client.get(BASE + '/' + trial['id']).status_code == 404
    assert submit(client).status_code == 403
    assert {r['state'] for r in query('SELECT state FROM guest_ai_subjects WHERE trial_id=%s', (trial['id'],))} == {'used'}
