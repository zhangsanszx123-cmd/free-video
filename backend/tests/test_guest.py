"""Guest allowance (2 links, cookie + IP) and its merge into the quota on login, against the real MySQL test DB."""
import pytest
from fastapi.testclient import TestClient

from app import account_store, config, downloader, guest, main, membership
from .test_accounts import db, register, login, query, PASSWORD

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason='MYSQL_TEST_DATABASE not configured')


@pytest.fixture(autouse=True)
def fresh(db, monkeypatch):
    query('DELETE FROM membership_plans')
    membership.seed()
    query('DELETE FROM guest_links')
    monkeypatch.setattr(downloader, 'parse', lambda url: {'url': 'https://canon.example/' + url.rsplit('/', 1)[-1],
                                                           'title': 'T', 'duration': 90.2, 'qualities': []})


def parse(client, name):
    return client.post('/api/parse', json={'url': f'https://share.example/{name}'})


def test_guest_gets_two_links_then_must_login(client):
    client.cookies.clear()
    assert parse(client, 'a').status_code == 200
    assert guest.COOKIE in client.cookies
    assert parse(client, 'a').status_code == 200          # same link again is free
    assert parse(client, 'b').status_code == 200
    blocked = parse(client, 'c')
    assert blocked.status_code == 403 and blocked.json()['code'] == 'GUEST_LIMIT'
    assert parse(client, 'b').status_code == 200          # known links keep working
    assert query('SELECT COUNT(*) AS n FROM guest_links WHERE subject LIKE %s', ('c:%',))[0]['n'] == 2


def test_clearing_cookie_does_not_reset_the_ip_allowance(client):
    client.cookies.clear()
    assert parse(client, 'a').status_code == 200 and parse(client, 'b').status_code == 200
    client.cookies.clear()
    assert parse(client, 'c').status_code == 403
    assert parse(client, 'a').status_code == 200          # IP already knows this link


def test_new_visitor_on_other_ip_is_independent(client):
    client.cookies.clear()
    assert parse(client, 'a').status_code == 200 and parse(client, 'b').status_code == 200
    other = TestClient(main.app, client=('203.0.113.9', 5000))
    assert parse(other, 'c').status_code == 200


def test_download_requires_a_parsed_link_and_other_features_need_login(client, monkeypatch):
    client.cookies.clear()
    monkeypatch.setattr(main.manager, 'submit', lambda *a, **k: type('J', (), {'to_dict': lambda self: {'id': 'job'}})())
    monkeypatch.setattr(main, 'read_subtitles', lambda *a: ({'title': 'T'}, [], {'source': 'platform_subtitle'}))
    body = {'url': 'https://canon.example/a', 'kind': 'video'}
    for path, payload in (('/api/download', body), ('/api/subtitles', {'url': body['url']}),
                          ('/api/transcript', {'url': body['url']}),
                          ('/api/transcriptions', {'url': body['url'], 'allow_asr': False})):
        denied = client.post(path, json=payload)
        assert denied.status_code == 403 and denied.json()['code'] == 'GUEST_LIMIT', path
    assert parse(client, 'a').status_code == 200
    assert client.post('/api/download', json=body).json() == {'id': 'job'}
    assert client.post('/api/subtitles', json={'url': body['url']}).json() == {'id': 'job'}
    assert client.post('/api/transcript', json={'url': body['url']}).status_code == 200
    assert client.post('/api/transcriptions', json={'url': body['url'], 'allow_asr': False}).status_code == 200
    for path, payload in (('/api/batch', {'urls': [body['url']], 'kind': 'audio'}),
                          ('/api/learn/summary', {'url': body['url']}), ('/api/ai/translate', {'url': body['url'], 'target_lang': 'English'})):
        assert client.post(path, json=payload).status_code == 401, path


def test_logged_in_user_is_not_limited(client):
    client.cookies.clear()
    assert register(client).status_code == 200
    assert all(parse(client, name).status_code == 200 for name in 'abcde')
    assert query('SELECT COUNT(*) AS n FROM guest_links')[0]['n'] == 0


def test_guest_duration_is_charged_once_on_register_and_login(client):
    client.cookies.clear()
    parse(client, 'a')
    parse(client, 'b')
    response = register(client)
    assert response.status_code == 200 and response.json()['guest_claimed_seconds'] == 2 * 91
    user = response.json()['user']['id']
    assert membership.summary(user)['used_seconds'] == 182
    client.post('/api/auth/logout')
    again = login(client)                      # same browser, nothing left to claim
    assert again.json()['guest_claimed_seconds'] == 0 and membership.summary(user)['used_seconds'] == 182
    client.post('/api/auth/logout')
    second = TestClient(main.app)
    second.cookies.set(guest.COOKIE, client.cookies.get(guest.COOKIE) or '')
    assert register(second, username='bobby1').json()['guest_claimed_seconds'] == 0


def test_claim_is_capped_by_remaining_quota(client):
    client.cookies.clear()
    parse(client, 'a')
    query("UPDATE guest_links SET duration_seconds=5000")
    response = register(client)
    assert response.json()['guest_claimed_seconds'] == 1800
    summary = membership.summary(response.json()['user']['id'])
    assert summary['used_seconds'] == 1800 and summary['available_seconds'] == 0


def test_forged_guest_cookie_is_ignored(client):
    client.cookies.clear()
    forged = 'abc.' + '0' * 64
    response = client.post('/api/parse', json={'url': 'https://share.example/a'}, headers={'cookie': f'{guest.COOKIE}={forged}'})
    assert response.status_code == 200
    assert guest.COOKIE + '=' in response.headers['set-cookie'] and forged not in response.headers['set-cookie']
