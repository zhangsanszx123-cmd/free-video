"""Admin permissions and account suspension against an isolated MySQL test database.

Run with MYSQL_TEST_DATABASE=freevideo_admin_test. Never point this suite at the
business database or run it alongside a browser backend sharing its test database.
Providers, mail, payments and their background reconciler are disabled by conftest.
"""
import json
import re
import sys
import threading
from datetime import timedelta

import pymysql
import pytest
from fastapi.testclient import TestClient

from app import account_auth, account_store, admin_auth, admin_store, config, email_verification, main, membership, payments, zpay
from app.errors import AccountError
from .test_accounts import PASSWORD, challenge, login as site_login, query, register, verification_mail


MAIN_DATABASE = config.MYSQL_DATABASE
REAL_INIT_SCHEMA = account_store.init_schema
REAL_ADMIN_INIT_SCHEMA = admin_store.init_schema
ADMIN_PASSWORD = 'Admin test password 2026'
NEW_PASSWORD = 'Changed admin password 2026'
pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason='MYSQL_TEST_DATABASE not configured')


@pytest.fixture(autouse=True)
def admin_database(tmp_downloads, monkeypatch):
    name = config.MYSQL_TEST_DATABASE
    assert name and re.fullmatch(r'[A-Za-z0-9_]+', name)
    assert name != MAIN_DATABASE and name not in ('freevideo', 'mysql', 'sys', 'information_schema', 'performance_schema')
    assert config.MYSQL_DATABASE == name
    # This suite deliberately exercises real authentication, not legacy feature-test overrides.
    main.app.dependency_overrides.pop(account_auth.require_user, None)
    main.app.dependency_overrides.pop(account_auth.current_user, None)
    monkeypatch.setattr(config, 'SESSION_SECURE', False)
    monkeypatch.setattr(config, 'AUTH_REGISTER_RATE_LIMIT', 500)
    monkeypatch.setattr(config, 'AUTH_LOGIN_RATE_LIMIT', 500)
    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                           password=config.MYSQL_PASSWORD, charset='utf8mb4')
    with conn, conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE IF NOT EXISTS `{name}` DEFAULT CHARACTER SET utf8mb4')
    REAL_INIT_SCHEMA()
    REAL_ADMIN_INIT_SCHEMA()
    for table in ('admin_audit_logs', 'admin_sessions', 'admin_users', 'admin_account_guard',
                  'payment_events', 'payment_orders', 'guest_links', 'sessions', 'users', 'membership_plans'):
        query(f'DELETE FROM {table}')
    REAL_ADMIN_INIT_SCHEMA()
    membership.seed()
    admin_auth.reset_limits()


def browser():
    return TestClient(main.app)


def admin_login(client, username='admin', password=ADMIN_PASSWORD):
    return client.post('/api/admin/auth/login', json={'username': username, 'password': password})


def public_admin(response):
    assert response.status_code == 200, response.text
    data = response.json()['admin']
    assert set(data) == {'id', 'username', 'nickname', 'role', 'status', 'created_at'}
    return data


@pytest.fixture
def superadmin():
    admin = admin_store.bootstrap('admin', 'Super admin', account_auth.hash_password(ADMIN_PASSWORD))
    client = browser()
    assert public_admin(admin_login(client))['id'] == admin['id']
    return client, admin


def staff(client, username='operator', role='admin', password=ADMIN_PASSWORD):
    return public_admin(client.post('/api/admin/staff', json={
        'username': username, 'password': password, 'nickname': 'Operator', 'role': role}))


def site_user(client=None, name='member'):
    client = client or browser()
    response = register(client, username=name)
    assert response.status_code == 200, response.text
    return client, response.json()['user']


def user_status(client, uid, status, reason=''):
    return client.patch(f'/api/admin/users/{uid}/status', json={'status': status, 'reason': reason})


def test_admin_history_reuses_existing_rows_and_preserves_site_isolation(superadmin):
    from app.transcriptions import Transcription
    client, _ = superadmin
    first, user = site_user(name='historyfirst')
    _, other = site_user(name='historysecond')
    now = account_store.utcnow()
    for index in range(25):
        job = Transcription(f'{index:032x}', f"user:{user['id'] if index % 2 else other['id']}",
                            f'{index:064x}', 'https://example.com/video', None, True,
                            status=('done', 'error', 'queued', 'running')[index % 4], title=f'测试记录 {index:02}',
                            result={'text': '文稿关键词', 'source': 'asr'})
        membership.create_record(job)
        membership.persist(job, {'platform': '测试平台', 'duration': 90})
        query('UPDATE transcription_records SET created_at=%s WHERE id=%s', (now - timedelta(seconds=index), job.id))
    query('UPDATE transcription_records SET hidden=TRUE WHERE id=%s', ('0' * 32,))
    query('UPDATE transcription_records SET expires_at=%s WHERE id=%s', (now - timedelta(seconds=1), f'{1:032x}'))
    assert browser().get('/api/admin/history').status_code == 401
    assert first.get('/api/admin/history').status_code == 401
    response = client.get('/api/admin/history')
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['total'] == 23 and len(data['items']) == 20
    assert data['items'][0]['title'] == '测试记录 02'
    assert {r['user_id'] for r in data['items']} == {user['id'], other['id']}
    assert {r['user_email'] for r in data['items']} == {user['email'], other['email']}
    assert all('fingerprint' not in row for row in data['items'])
    assert len(client.get('/api/admin/history?page=2').json()['items']) == 3
    assert client.get('/api/admin/history?search=测试记录 24').json()['total'] == 1
    assert client.get('/api/admin/history?search=文稿关键词').json()['total'] == 23
    active = client.get('/api/admin/history?status=active').json()
    assert active['total'] == 12 and {r['status'] for r in active['items']} == {'queued', 'running'}
    own = first.get('/api/account/history').json()
    assert own['total'] == 11 and all('user_id' not in r and 'user_email' not in r for r in own['items'])
    staff(client); operator = browser(); admin_login(operator, 'operator')
    assert operator.get('/api/admin/history').json()['total'] == 23
    assert client.get('/api/admin/history?status=invalid').status_code == 422
    assert client.get('/api/admin/history?page=0').status_code == 422


def limits_body(plan, **overrides):
    return dict(revision=plan['revision'], monthly_minutes=plan['monthly_seconds'] // 60,
                ai_monthly_limit=plan['ai_monthly_limit'], chat_daily_limit=plan['chat_daily_limit'],
                batch_max_links=plan['batch_max_links'], asr_max_minutes=plan['asr_max_minutes'], **overrides)


@pytest.mark.parametrize('code', ['free', 'monthly', 'yearly'])
def test_live_plan_limits_preserve_usage_and_holds(superadmin, code):
    from app import usage, transcriptions
    from app.errors import TranscriptionError
    client, _ = superadmin
    _, user = site_user()
    uid = user['id']
    if code != 'free': membership.grant(user['email'], code)
    membership.reserve(uid, 'spent', 100, 'a' * 64)
    membership.finalize(uid, 'spent', 'settled')
    membership.reserve(uid, 'held', 200, 'b' * 64)
    before = membership.summary(uid)
    original = next(p for p in membership.plans() if p['code'] == code)
    body = dict(revision=original['revision'], monthly_minutes=1, ai_monthly_limit=1,
                chat_daily_limit=1, batch_max_links=2, asr_max_minutes=1)
    result = client.patch(f'/api/admin/plan-limits/{code}', json=body)
    assert result.status_code == 200, result.text
    assert result.json()['plan']['price_cents'] == original['price_cents']
    current = membership.summary(uid)
    assert current['limit_seconds'] == 60 and current['available_seconds'] == 0
    assert current['used_seconds'] == before['used_seconds'] == 100
    assert current['reserved_seconds'] == before['reserved_seconds'] == 200
    assert main.batch_cap(uid)[0] == 2 and transcriptions.max_seconds(uid) == 60
    with pytest.raises(TranscriptionError): membership.reserve(uid, 'new', 1, 'c' * 64)
    ticket = usage.ai_begin(uid, 'https://example.com/1'); usage.ai_commit(ticket)
    with pytest.raises(AccountError): usage.ai_begin(uid, 'https://example.com/2')
    usage.chat_begin(uid)
    with pytest.raises(AccountError): usage.chat_begin(uid)
    body.update(revision=result.json()['plan']['revision'], monthly_minutes=10)
    assert client.patch(f'/api/admin/plan-limits/{code}', json=body).status_code == 200
    assert membership.summary(uid)['available_seconds'] == 300
    membership.finalize(uid, 'held', 'settled')
    after = membership.summary(uid)
    assert after['used_seconds'] == 300 and after['reserved_seconds'] == 0
    assert after['available_seconds'] == 300
    assert len(query("SELECT * FROM admin_audit_logs WHERE action='plan.limits_update'")) == 2


def test_plan_limit_permissions_validation_and_conflict(superadmin, monkeypatch):
    client, _ = superadmin
    original = membership.plans()[0]
    body = limits_body(original)
    assert browser().get('/api/admin/plan-limits').status_code == 401
    assert len(client.get('/api/admin/plan-limits').json()['plans']) == 3
    staff(client); operator = browser(); admin_login(operator, 'operator')
    assert operator.get('/api/admin/plan-limits').status_code == 200
    assert operator.patch('/api/admin/plan-limits/free', json=body).status_code == 403
    assert client.patch('/api/admin/plan-limits/free', json=body, headers={'origin': 'https://evil.example'}).status_code == 403
    for patch in ({'monthly_minutes': 0}, {'monthly_minutes': 1.5}, {'ai_monthly_limit': True},
                  {'batch_max_links': config.MAX_BATCH + 1}, {'asr_max_minutes': config.ASR_MAX_DURATION // 60 + 1}, {'price_cents': 1}):
        assert client.patch('/api/admin/plan-limits/free', json={**body, **patch}).status_code == 422
    body['monthly_minutes'] += 1
    assert client.patch('/api/admin/plan-limits/free', json=body).status_code == 200
    assert client.patch('/api/admin/plan-limits/free', json=body).status_code == 409
    def fail(*args, **kwargs): raise AccountError('AUDIT_FAILED', '审计失败', 503)
    monkeypatch.setattr(admin_store, '_audit', fail)
    body['revision'] += 1; body['monthly_minutes'] += 1
    current = membership.plans()
    assert client.patch('/api/admin/plan-limits/free', json=body).status_code == 503
    assert membership.plans() == current


def test_plan_price_permissions_and_audit(superadmin):
    client, owner = superadmin
    assert browser().get('/api/admin/plans').status_code == 401
    plain, _ = site_user()
    assert plain.get('/api/admin/plans').status_code == 401
    staff(client)
    operator = browser()
    assert admin_login(operator, 'operator').status_code == 200
    original = next(p for p in membership.plans() if p['code'] == 'monthly')
    body = {'price_cents': 2990, 'revision': original['revision']}
    assert operator.get('/api/admin/plans').status_code == 200
    assert operator.patch('/api/admin/plans/monthly/price', json=body).status_code == 403
    response = client.patch('/api/admin/plans/monthly/price', json=body)
    assert response.status_code == 200, response.text
    updated = response.json()['plan']
    assert updated == {**original, 'price_cents': 2990, 'revision': original['revision'] + 1}
    assert next(p for p in client.get('/api/plans').json()['plans'] if p['code'] == 'monthly') == updated
    audit = query("SELECT * FROM admin_audit_logs WHERE action='plan.price_update'")
    assert len(audit) == 1 and audit[0]['actor_id'] == owner['id']
    detail = json.loads(audit[0]['detail'])
    assert detail['before']['price_cents'] == original['price_cents']
    assert detail['after']['price_cents'] == 2990
    assert client.patch('/api/admin/plans/monthly/price', json=body).status_code == 409
    assert client.patch('/api/admin/plans/monthly/price', json={'price_cents': 2990, 'revision': updated['revision']}).status_code == 200
    assert len(query("SELECT * FROM admin_audit_logs WHERE action='plan.price_update'")) == 1


@pytest.mark.parametrize('value', [0, -1, 100000000, 19.9, '1990', True])
def test_invalid_plan_prices(superadmin, value):
    client, _ = superadmin
    assert client.patch('/api/admin/plans/monthly/price', json={'price_cents': value, 'revision': 1}).status_code == 422
    assert not query("SELECT * FROM admin_audit_logs WHERE action='plan.price_update'")


def test_plan_price_origin_and_scope(superadmin):
    client, _ = superadmin
    body = {'price_cents': 10900, 'revision': 1}
    assert client.patch('/api/admin/plans/yearly/price', json=body, headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.patch('/api/admin/plans/free/price', json=body).status_code == 422
    assert client.patch('/api/admin/plans/yearly/price', json={**body, 'monthly_seconds': 1}).status_code == 422
    assert client.patch('/api/admin/plans/yearly/price', json=body).status_code == 200
    assert next(p for p in membership.plans() if p['code'] == 'yearly')['price_cents'] == 10900


def test_price_update_audit_failure_rolls_back(superadmin, monkeypatch):
    client, _ = superadmin
    original = membership.plans()
    def fail(*args, **kwargs):
        raise AccountError('AUDIT_FAILED', '审计失败', 503)
    monkeypatch.setattr(admin_store, '_audit', fail)
    assert client.patch('/api/admin/plans/monthly/price', json={'price_cents': 2990, 'revision': 1}).status_code == 503
    assert membership.plans() == original


def test_concurrent_plan_price_changes(superadmin):
    client, _ = superadmin
    barrier = threading.Barrier(2)
    results = []
    def update(amount):
        other = browser()
        other.cookies.update(client.cookies)
        barrier.wait()
        results.append(other.patch('/api/admin/plans/monthly/price', json={'price_cents': amount, 'revision': 1}).status_code)
    threads = [threading.Thread(target=update, args=(amount,)) for amount in (2990, 3990)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=10)
    assert sorted(results) == [200, 409]
    assert len(query("SELECT * FROM admin_audit_logs WHERE action='plan.price_update'")) == 1


def test_bootstrap_is_explicit_and_never_overwrites_an_existing_account():
    assert query('SELECT id FROM admin_users') == ()
    first = admin_store.bootstrap('admin', 'First owner', account_auth.hash_password(ADMIN_PASSWORD))
    stored = query('SELECT password_hash FROM admin_users WHERE id=%s', (first['id'],))[0]['password_hash']
    for username in ('admin', 'anotheradmin'):
        with pytest.raises(AccountError) as failure:
            admin_store.bootstrap(username, 'Replacement', account_auth.hash_password(NEW_PASSWORD))
        assert failure.value.code == 'ADMIN_ALREADY_INITIALIZED'
    assert len(query('SELECT id FROM admin_users')) == 1
    assert query('SELECT password_hash FROM admin_users')[0]['password_hash'] == stored
    assert account_auth.verify_password(ADMIN_PASSWORD, stored)
    assert not account_auth.verify_password(NEW_PASSWORD, stored)


@pytest.mark.parametrize('method,path,body', [
    ('get', '/api/admin/users', None), ('get', '/api/admin/users/1', None),
    ('patch', '/api/admin/users/1/status', {'status': 'disabled'}),
    ('get', '/api/admin/staff', None),
    ('post', '/api/admin/staff', {'username': 'rogue', 'password': ADMIN_PASSWORD, 'nickname': 'Rogue', 'role': 'superadmin'}),
    ('patch', '/api/admin/staff/1', {'role': 'superadmin'}),
    ('post', '/api/admin/staff/1/password', {'password': ADMIN_PASSWORD}),
])
def test_registered_users_and_guests_have_no_admin_permissions(superadmin, method, path, body):
    for client in (browser(), site_user()[0]):
        response = getattr(client, method)(path, **({'json': body} if body is not None else {}))
        assert response.status_code == 401 and response.json()['code'] == 'ADMIN_AUTH_REQUIRED'
        assert response.headers['cache-control'] == 'no-store'
    assert len(query('SELECT id FROM admin_users')) == 1


def test_login_cookie_and_database_never_expose_password_or_session_token(superadmin):
    client, admin = superadmin
    response = admin_login(client, 'ADMIN')
    assert public_admin(response)['id'] == admin['id']
    cookie = response.headers['set-cookie'].lower()
    assert 'freevideo_admin=' in cookie and 'httponly' in cookie
    assert 'path=/api/admin' in cookie and 'samesite=lax' in cookie
    assert 'freevideo_auth=' not in cookie
    token = client.cookies.get(admin_auth.COOKIE)
    sessions = query('SELECT token_hash FROM admin_sessions WHERE admin_id=%s', (admin['id'],))
    assert any(row['token_hash'] == account_auth.token_hash(token) for row in sessions)
    assert all(row['token_hash'] != token for row in sessions)
    assert ADMIN_PASSWORD not in response.text and 'password_hash' not in response.text


def test_frontend_and_admin_logins_and_logouts_are_independent(superadmin):
    client, _ = superadmin
    _, user = site_user(client)
    assert client.get('/api/auth/me').json()['user']['id'] == user['id']
    assert client.get('/api/admin/auth/me').json()['admin']['role'] == 'superadmin'
    client.post('/api/auth/logout')
    assert client.get('/api/auth/me').json()['user'] is None
    assert client.get('/api/admin/auth/me').json()['admin'] is not None
    assert site_login(client).status_code == 401  # a different site username is not an admin identity
    assert site_login(client, username='member').status_code == 200
    client.post('/api/admin/auth/logout')
    assert client.get('/api/admin/auth/me').json()['admin'] is None
    assert client.get('/api/auth/me').json()['user']['id'] == user['id']
    assert admin_login(browser(), password=PASSWORD).status_code == 401


def test_user_list_pagination_filters_search_and_detail_whitelist(superadmin):
    client, _ = superadmin
    for index in range(23):
        site_user(name=f'member{index:02d}')
    target = query("SELECT id FROM users WHERE email='member07@example.com'")[0]['id']
    assert user_status(client, target, 'disabled', 'test suspension').status_code == 200
    query('UPDATE users SET email_verified=0 WHERE email=%s', ('member08@example.com',))
    first = client.get('/api/admin/users').json()
    second = client.get('/api/admin/users', params={'page': 2}).json()
    assert first['total'] == second['total'] == 23 and first['page_size'] == 20
    assert len(first['items']) == 20 and len(second['items']) == 3
    assert not ({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
    result = client.get('/api/admin/users', params={'search': 'member07@example.com'}).json()
    assert [row['id'] for row in result['items']] == [target]
    # A numeric query may also match digits in another email/nickname.
    result = client.get('/api/admin/users', params={'search': str(target)}).json()
    assert target in {row['id'] for row in result['items']}
    query('UPDATE users SET nickname=%s WHERE id=%s', ('Distinct Chinese 昵称', target))
    chinese = client.get('/api/admin/users', params={'search': 'Chinese 昵称'})
    assert chinese.status_code == 200, chinese.text
    assert chinese.json()['total'] == 1
    assert client.get('/api/admin/users', params={'status': 'disabled'}).json()['total'] == 1
    assert client.get('/api/admin/users', params={'verified': 'pending'}).json()['total'] == 1
    assert client.get('/api/admin/users', params={'search': "' OR 1=1 --"}).json()['total'] == 0
    detail = client.get(f'/api/admin/users/{target}').json()
    assert set(detail) == {'id', 'email', 'nickname', 'created_at', 'email_verified', 'status',
                           'disabled_at', 'disabled_reason', 'membership'}
    assert detail['status'] == 'disabled' and detail['disabled_reason'] == 'test suspension'
    assert 'password' not in json.dumps(first) and 'token' not in json.dumps(detail)
    assert client.get('/api/admin/users/999999999').status_code == 404
    assert client.get('/api/admin/users', params={'page': 0}).status_code == 422


def test_ordinary_admin_can_manage_registered_users_but_not_staff(superadmin):
    owner, _ = superadmin
    operator = staff(owner)
    client = browser()
    public_admin(admin_login(client, operator['username']))
    _, user = site_user()
    assert client.get('/api/admin/users').status_code == 200
    assert client.get(f"/api/admin/users/{user['id']}").status_code == 200
    assert user_status(client, user['id'], 'disabled').status_code == 200
    assert user_status(client, user['id'], 'active').status_code == 200
    requests = [
        ('get', '/api/admin/staff', None),
        ('post', '/api/admin/staff', {'username': 'rogue', 'nickname': 'Rogue', 'password': ADMIN_PASSWORD, 'role': 'superadmin'}),
        ('patch', f"/api/admin/staff/{operator['id']}", {'role': 'superadmin'}),
        ('post', '/api/admin/staff/1/password', {'password': NEW_PASSWORD}),
    ]
    for method, path, body in requests:
        response = getattr(client, method)(path, **({'json': body} if body else {}))
        assert response.status_code == 403 and response.json()['code'] == 'ADMIN_FORBIDDEN'
    assert len(query('SELECT id FROM admin_users')) == 2


def test_superadmin_staff_validation_and_case_insensitive_unique_names(superadmin):
    client, _ = superadmin
    created = staff(client)
    duplicate = client.post('/api/admin/staff', json={'username': 'OPERATOR', 'nickname': 'Other',
                                                    'password': ADMIN_PASSWORD, 'role': 'admin'})
    assert duplicate.status_code == 409
    for changes in ({'role': 'owner'}, {'status': 'deleted'}, {'nickname': ''}):
        assert client.patch(f"/api/admin/staff/{created['id']}", json=changes).status_code == 422
    assert client.post('/api/admin/staff', json={'username': 'bad name', 'nickname': 'Bad',
                                                'password': 'short', 'role': 'admin'}).status_code == 422
    assert client.patch(f"/api/admin/staff/{created['id']}", json={'nickname': 'Changed'}).status_code == 200
    result = client.get('/api/admin/staff', params={'search': 'Changed'}).json()
    assert result['total'] == 1 and result['items'][0]['id'] == created['id']
    exact_id = client.get('/api/admin/staff', params={'search': str(created['id'])}).json()
    assert exact_id['total'] == 1 and exact_id['items'][0]['id'] == created['id']
    assert client.patch(f"/api/admin/staff/{created['id']}", json={'nickname': '中文管理员甲'}).status_code == 200
    chinese = client.get('/api/admin/staff', params={'search': '管理员甲'})
    assert chinese.status_code == 200, chinese.text
    assert chinese.json()['total'] == 1 and chinese.json()['items'][0]['id'] == created['id']


def test_admin_password_change_revokes_all_admin_sessions_only(superadmin):
    client, _ = superadmin
    _, user = site_user(client)
    other = browser()
    public_admin(admin_login(other))
    result = client.post('/api/admin/auth/password', json={'old_password': ADMIN_PASSWORD, 'new_password': NEW_PASSWORD})
    assert result.status_code == 200
    assert client.get('/api/admin/auth/me').json()['admin'] is None
    assert other.get('/api/admin/users').status_code == 401
    assert client.get('/api/auth/me').json()['user']['id'] == user['id']
    assert admin_login(browser()).status_code == 401
    assert admin_login(browser(), password=NEW_PASSWORD).status_code == 200


def test_reset_disable_and_enable_staff_do_not_revive_old_sessions(superadmin):
    owner, _ = superadmin
    operator = staff(owner)
    client, another = browser(), browser()
    public_admin(admin_login(client, 'operator'))
    public_admin(admin_login(another, 'operator'))
    old_token = client.cookies.get(admin_auth.COOKIE)
    assert owner.post(f"/api/admin/staff/{operator['id']}/password", json={'password': NEW_PASSWORD}).status_code == 200
    assert client.get('/api/admin/users').status_code == another.get('/api/admin/users').status_code == 401
    assert admin_login(client, 'operator', NEW_PASSWORD).status_code == 200
    assert owner.patch(f"/api/admin/staff/{operator['id']}", json={'status': 'disabled'}).status_code == 200
    assert client.get('/api/admin/users').status_code in (401, 403)
    assert admin_login(browser(), 'operator', NEW_PASSWORD).json()['code'] == 'ADMIN_DISABLED'
    assert owner.patch(f"/api/admin/staff/{operator['id']}", json={'status': 'active'}).status_code == 200
    stale = browser()
    stale.cookies.set(admin_auth.COOKIE, old_token, path='/api/admin')
    assert stale.get('/api/admin/users').status_code == 401
    assert admin_login(browser(), 'operator', NEW_PASSWORD).status_code == 200


def test_current_database_role_is_checked_instead_of_a_session_snapshot(superadmin):
    owner, _ = superadmin
    operator = staff(owner, role='superadmin')
    client = browser()
    public_admin(admin_login(client, 'operator'))
    assert client.get('/api/admin/staff').status_code == 200
    # Keep the session deliberately, proving every request reads the current account role.
    query('UPDATE admin_users SET role=%s WHERE id=%s', ('admin', operator['id']))
    response = client.get('/api/admin/staff')
    assert response.status_code == 403 and response.json()['code'] == 'ADMIN_FORBIDDEN'
    assert client.get('/api/admin/users').status_code == 200


def test_staff_write_rechecks_actor_after_request_authentication(superadmin, monkeypatch):
    owner, _ = superadmin
    operator = staff(owner, role='superadmin')
    client = browser()
    public_admin(admin_login(client, 'operator'))
    original = admin_store.create_staff
    def interleaved(*args, **kwargs):
        # The request has passed require_superadmin, but that privilege is now revoked.
        assert owner.patch(f"/api/admin/staff/{operator['id']}", json={'role': 'admin'}).status_code == 200
        return original(*args, **kwargs)
    monkeypatch.setattr(admin_store, 'create_staff', interleaved)
    response = client.post('/api/admin/staff', json={'username': 'latecreate', 'nickname': 'Late',
                                                   'password': ADMIN_PASSWORD, 'role': 'superadmin'})
    assert response.status_code in (401, 403)
    assert not query('SELECT id FROM admin_users WHERE username_key=%s', ('latecreate',))


def test_local_password_recovery_revokes_admin_sessions_without_default_credentials(superadmin):
    client, owner = superadmin
    admin_store.cli_reset_password('admin', account_auth.hash_password(NEW_PASSWORD))
    assert not query('SELECT id FROM admin_sessions WHERE admin_id=%s', (owner['id'],))
    assert client.get('/api/admin/users').status_code == 401
    assert admin_login(browser()).status_code == 401
    assert admin_login(browser(), password=NEW_PASSWORD).status_code == 200
    assert len(query('SELECT id FROM admin_users')) == 1


def test_bootstrap_cli_uses_hidden_input_and_does_not_print_a_password(monkeypatch, capsys):
    prompts = []
    def hidden_input(prompt):
        prompts.append(prompt)
        return ADMIN_PASSWORD
    monkeypatch.setattr(admin_auth, 'getpass', hidden_input)
    monkeypatch.setattr(sys, 'argv', ['admin_auth', 'bootstrap', '--username', 'admin'])
    admin_auth.main()
    output = capsys.readouterr()
    assert len(prompts) == 2
    assert ADMIN_PASSWORD not in output.out + output.err
    assert account_auth.verify_password(ADMIN_PASSWORD, admin_store.get_credentials('admin')['password_hash'])


def test_bootstrap_cli_password_mismatch_creates_no_account(monkeypatch, capsys):
    answers = iter([ADMIN_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr(admin_auth, 'getpass', lambda _: next(answers))
    monkeypatch.setattr(sys, 'argv', ['admin_auth', 'bootstrap'])
    with pytest.raises(SystemExit) as failure:
        admin_auth.main()
    assert failure.value.code == 1
    assert not query('SELECT id FROM admin_users')
    output = capsys.readouterr()
    assert ADMIN_PASSWORD not in output.out + output.err and NEW_PASSWORD not in output.out + output.err


def test_admin_login_lockout_does_not_lock_the_site_account(superadmin):
    _, _ = superadmin
    site_client, user = site_user(name='admin')
    client = browser()
    known = admin_login(client, password='wrong password')
    unknown = admin_login(client, username='missingadmin', password='wrong password')
    assert known.status_code == unknown.status_code == 401 and known.json() == unknown.json()
    for _ in range(4):
        assert admin_login(client, password='wrong password').status_code == 401
    blocked = admin_login(client)
    assert blocked.status_code == 429 and blocked.json()['code'] == 'ADMIN_RATE_LIMIT'
    site_client.post('/api/auth/logout')
    assert site_login(site_client, 'admin').status_code == 200
    assert site_client.get('/api/auth/me').json()['user']['id'] == user['id']


def test_self_disable_and_last_superadmin_demotion_are_refused(superadmin):
    client, owner = superadmin
    assert client.patch(f"/api/admin/staff/{owner['id']}", json={'status': 'disabled'}).json()['code'] == 'ADMIN_SELF_DISABLE'
    response = client.patch(f"/api/admin/staff/{owner['id']}", json={'role': 'admin'})
    assert response.status_code == 409 and response.json()['code'] == 'ADMIN_LAST_SUPERADMIN'
    assert client.get('/api/admin/staff').status_code == 200


def test_concurrent_superadmin_demotions_always_keep_an_enabled_superadmin(superadmin):
    first, owner = superadmin
    second_admin = staff(first, 'secondowner', 'superadmin')
    second = browser()
    public_admin(admin_login(second, 'secondowner'))
    barrier = threading.Barrier(2)
    outcomes, failures = [], []
    def demote(client, target):
        try:
            barrier.wait(timeout=5)
            outcomes.append(client.patch(f'/api/admin/staff/{target}', json={'role': 'admin'}).status_code)
        except Exception as exc:  # surfaced in the main test, never lost in a worker
            failures.append(exc)
    threads = [threading.Thread(target=demote, args=args) for args in
               ((first, second_admin['id']), (second, owner['id']))]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)
    assert not failures and outcomes.count(200) == 1
    assert all(code in (200, 401, 403, 409) for code in outcomes)
    assert query("SELECT COUNT(*) AS n FROM admin_users WHERE role='superadmin' AND status='active'")[0]['n'] == 1


@pytest.mark.parametrize('change', ['disable', 'password'])
def test_admin_login_rechecks_credentials_after_verification(superadmin, monkeypatch, change):
    owner, _ = superadmin
    operator = staff(owner)
    original = admin_store.create_session
    def interleaved(*args, **kwargs):
        if change == 'disable':
            result = owner.patch(f"/api/admin/staff/{operator['id']}", json={'status': 'disabled'})
        else:
            result = owner.post(f"/api/admin/staff/{operator['id']}/password", json={'password': NEW_PASSWORD})
        assert result.status_code == 200
        return original(*args, **kwargs)
    monkeypatch.setattr(admin_store, 'create_session', interleaved)
    response = admin_login(browser(), 'operator')
    assert response.status_code in (401, 403)
    assert not query('SELECT id FROM admin_sessions WHERE admin_id=%s', (operator['id'],))


def test_registered_user_disable_rechecks_login_and_revokes_all_sessions(superadmin, monkeypatch):
    owner, _ = superadmin
    client, user = site_user()
    another = browser()
    assert site_login(another, 'member').status_code == 200
    original = account_store.create_session
    def interleaved(*args, **kwargs):
        assert user_status(owner, user['id'], 'disabled', 'review').status_code == 200
        return original(*args, **kwargs)
    monkeypatch.setattr(account_store, 'create_session', interleaved)
    response = site_login(browser(), 'member')
    assert response.status_code == 403 and response.json()['code'] == 'USER_DISABLED'
    assert not query('SELECT id FROM sessions WHERE user_id=%s', (user['id'],))
    for device in (client, another):
        assert device.get('/api/auth/me').json()['user'] is None
        assert device.get('/api/account/membership').status_code == 401


def test_disabled_pending_user_cannot_use_email_links_or_receive_new_links(superadmin, verification_mail):
    owner, _ = superadmin
    client = browser()
    assert register(client, 'pending').json()['verification_required']
    verification_token = verification_mail[-1][1].split('#token=')[1]
    assert client.post('/api/auth/forgot-password', json={'email': 'pending@example.com'}).status_code == 200
    recovery_token = verification_mail[-1][1].split('#token=')[1]
    before = query('SELECT * FROM users WHERE email=%s', ('pending@example.com',))[0]
    assert user_status(owner, before['id'], 'disabled', 'pending user').status_code == 200
    assert not query('SELECT user_id FROM email_verifications') and not query('SELECT user_id FROM password_resets')
    assert client.post('/api/auth/verify-email', json={'token': verification_token}).json()['code'] == 'INVALID_VERIFICATION_LINK'
    assert client.post('/api/auth/reset-password', json={'token': recovery_token, 'password': NEW_PASSWORD}).json()['code'] == 'INVALID_RESET_LINK'
    sent = len(verification_mail)
    account_auth.reset_limits()
    assert client.post('/api/auth/forgot-password', json={'email': 'pending@example.com'}).status_code == 200
    assert client.post('/api/auth/resend-verification', json={'email': 'pending@example.com', 'password': PASSWORD}).status_code == 403
    assert len(verification_mail) == sent
    assert user_status(owner, before['id'], 'active').status_code == 200
    after = query('SELECT * FROM users WHERE id=%s', (before['id'],))[0]
    assert not after['email_verified'] and after['created_at'] == before['created_at']
    assert not query('SELECT id FROM sessions WHERE user_id=%s', (before['id'],))
    assert site_login(client, 'pending').json()['code'] == 'EMAIL_NOT_VERIFIED'


def test_email_flows_recheck_disabled_state_even_with_cached_credentials_and_surviving_tokens(superadmin, verification_mail, monkeypatch):
    owner, _ = superadmin
    client = browser()
    assert register(client, 'pending').json()['verification_required']
    verification_token = verification_mail[-1][1].split('#token=')[1]
    client.post('/api/auth/forgot-password', json={'email': 'pending@example.com'})
    recovery_token = verification_mail[-1][1].split('#token=')[1]
    cached = account_store.get_email_credentials('pending@example.com')
    verification = query('SELECT * FROM email_verifications WHERE user_id=%s', (cached['id'],))[0]
    recovery = query('SELECT * FROM password_resets WHERE user_id=%s', (cached['id'],))[0]
    assert user_status(owner, cached['id'], 'disabled').status_code == 200
    # Model tokens retained by a legacy caller, independently of the normal revocation cleanup.
    for table, saved in (('email_verifications', verification), ('password_resets', recovery)):
        columns = ','.join(saved)
        placeholders = ','.join(['%s'] * len(saved))
        query(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})', tuple(saved.values()))
    assert client.post('/api/auth/verify-email', json={'token': verification_token}).json()['code'] == 'USER_DISABLED'
    assert client.post('/api/auth/reset-password', json={'token': recovery_token, 'password': NEW_PASSWORD}).json()['code'] == 'INVALID_RESET_LINK'
    before_sent = len(verification_mail)
    with pytest.raises(AccountError) as failure:
        email_verification.send(cached)
    assert failure.value.code == 'USER_DISABLED'
    account_auth.reset_limits()
    monkeypatch.setattr(account_store, 'get_email_credentials', lambda _: cached)
    query('DELETE FROM password_resets WHERE user_id=%s', (cached['id'],))
    assert client.post('/api/auth/forgot-password', json={'email': 'pending@example.com'}).status_code == 200
    assert len(verification_mail) == before_sent and not query('SELECT user_id FROM password_resets')
    current = query('SELECT email_verified,password_hash FROM users WHERE id=%s', (cached['id'],))[0]
    assert not current['email_verified'] and current['password_hash'] == cached['password_hash']
    assert not query('SELECT id FROM sessions WHERE user_id=%s', (cached['id'],))


def test_enable_keeps_membership_orders_usage_and_old_sessions_invalid(superadmin, monkeypatch):
    owner, _ = superadmin
    client, user = site_user()
    old_token = client.cookies.get(account_auth.COOKIE)
    membership.grant(user['email'], 'monthly')
    membership.reserve(user['id'], 'f' * 32, 120, 'a' * 64)
    membership.finalize(user['id'], 'f' * 32, 'settled')
    monkeypatch.setattr(zpay, 'enabled', lambda: True)
    monkeypatch.setattr(zpay, 'submit_form', lambda *args: ('https://gateway.invalid/submit.php', {}))
    payments.create_order(user['id'], 'monthly')  # signed-form creation has no network side effect
    now = account_store.utcnow()
    query('INSERT INTO transcription_records '
          '(id,user_id,fingerprint,url,payload,status,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
          ('e' * 32, user['id'], 'b' * 64, 'https://example.test/history',
           json.dumps({'status': 'done', 'text': 'Saved transcript'}), 'done', now, now + timedelta(days=30)))
    tables = ('user_memberships', 'user_quota_periods', 'quota_reservations', 'quota_events',
              'payment_orders', 'payment_events', 'transcription_records')
    snapshots = {table: query(f'SELECT * FROM {table}') for table in tables}
    created = query('SELECT created_at,email_verified FROM users WHERE id=%s', (user['id'],))[0]
    assert user_status(owner, user['id'], 'disabled', 'test hold').status_code == 200
    assert user_status(owner, user['id'], 'active').status_code == 200
    assert {table: query(f'SELECT * FROM {table}') for table in tables} == snapshots
    assert query('SELECT created_at,email_verified FROM users WHERE id=%s', (user['id'],))[0] == created
    stale = browser()
    stale.cookies.set(account_auth.COOKIE, old_token, path='/api')
    assert stale.get('/api/auth/me').json()['user'] is None
    assert site_login(browser(), 'member').status_code == 200


@pytest.mark.parametrize('method,path,body', [
    ('post', '/api/admin/auth/login', {'username': 'admin', 'password': ADMIN_PASSWORD}),
    ('post', '/api/admin/auth/logout', {}),
    ('post', '/api/admin/auth/password', {'old_password': ADMIN_PASSWORD, 'new_password': NEW_PASSWORD}),
    ('post', '/api/admin/staff', {'username': 'other', 'nickname': 'Other', 'password': NEW_PASSWORD, 'role': 'admin'}),
    ('patch', '/api/admin/staff/1', {'nickname': 'Changed'}),
    ('post', '/api/admin/staff/1/password', {'password': NEW_PASSWORD}),
    ('patch', '/api/admin/users/1/status', {'status': 'disabled'}),
])
def test_admin_writes_reject_cross_site_requests(superadmin, method, path, body):
    client, _ = superadmin
    response = getattr(client, method)(path, json=body, headers={'origin': 'https://evil.example'})
    assert response.status_code == 403
    assert len(query('SELECT id FROM admin_users')) == 1
    assert client.get('/api/admin/staff').status_code == 200


def test_schema_initialization_is_idempotent_and_audits_exclude_credentials(superadmin):
    client, _ = superadmin
    operator = staff(client)
    assert client.post(f"/api/admin/staff/{operator['id']}/password", json={'password': NEW_PASSWORD}).status_code == 200
    _, user = site_user()
    assert user_status(client, user['id'], 'disabled', 'manual review').status_code == 200
    before = query('SELECT * FROM admin_users')
    REAL_INIT_SCHEMA()
    REAL_ADMIN_INIT_SCHEMA()
    assert query('SELECT * FROM admin_users') == before
    assert query('SELECT status FROM users WHERE id=%s', (user['id'],))[0]['status'] == 'disabled'
    logs = query('SELECT * FROM admin_audit_logs')
    assert logs
    serialized = json.dumps(logs, default=str)
    assert ADMIN_PASSWORD not in serialized and NEW_PASSWORD not in serialized
    assert 'scrypt$' not in serialized and client.cookies.get(admin_auth.COOKIE) not in serialized


def test_admin_session_expiry_and_database_failure_are_reported_without_site_logout(superadmin, monkeypatch):
    client, owner = superadmin
    _, user = site_user(client)
    query('UPDATE admin_sessions SET expires_at=%s WHERE admin_id=%s',
          (account_store.utcnow() - timedelta(seconds=1), owner['id']))
    assert client.get('/api/admin/users').status_code == 401
    assert client.get('/api/auth/me').json()['user']['id'] == user['id']
    assert admin_login(client).status_code == 200
    monkeypatch.setattr(config, 'MYSQL_PORT', 1)
    response = client.get('/api/admin/auth/me')
    assert response.status_code == 503 and 'password' not in response.text.lower()
