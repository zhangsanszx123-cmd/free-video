"""Account API tests against a real, dedicated MySQL test database (MYSQL_TEST_DATABASE)."""
import threading
from datetime import timedelta

import pymysql
import pytest
from fastapi.testclient import TestClient

from app import account_auth, account_store, config, main, captcha, email_verification
from app.errors import AccountError

MAIN_DATABASE = config.MYSQL_DATABASE
REAL_INIT_SCHEMA = account_store.init_schema
PASSWORD = "correct horse 9"

def challenge(client):
    from unittest.mock import patch
    with patch.object(captcha, "_problem", return_value=("6-4=?", "2")):
        result = client.get("/api/auth/captcha").json()
    return {"captcha_id": result["id"], "captcha_answer": "2"}

def email_for(value):
    return value if "@" in value else value + "@example.com"

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason="MYSQL_TEST_DATABASE not configured")


@pytest.fixture(autouse=True)
def db(monkeypatch):
    assert config.MYSQL_TEST_DATABASE != MAIN_DATABASE, "MYSQL_TEST_DATABASE must differ from MYSQL_DATABASE"
    monkeypatch.setattr(config, "AUTH_REGISTER_RATE_LIMIT", 5)
    monkeypatch.setattr(config, "AUTH_LOGIN_RATE_LIMIT", 10)
    main.app.dependency_overrides.pop(account_auth.require_user, None)
    main.app.dependency_overrides.pop(account_auth.current_user, None)
    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                           password=config.MYSQL_PASSWORD, charset="utf8mb4")
    with conn, conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL_TEST_DATABASE}` DEFAULT CHARACTER SET utf8mb4")
    REAL_INIT_SCHEMA()
    with account_store._cursor() as cur:
        cur.execute("DELETE FROM sessions")
        cur.execute("DELETE FROM users")


def make_client():
    return TestClient(main.app)


def register(client, username="alice", password=PASSWORD, **extra):
    return client.post("/api/auth/register", json={"email": email_for(username), "password": password, **extra, **challenge(client)})


def login(client, username="alice", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email_for(username), "password": password, **challenge(client)})


def query(sql, args=()):
    with account_store._cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def test_password_hash_roundtrip():
    stored = account_auth.hash_password("pässwörd 123")
    assert stored.startswith("scrypt$16384$8$1$")
    assert account_auth.verify_password("pässwörd 123", stored)
    assert not account_auth.verify_password("pässwörd 124", stored)
    assert not account_auth.verify_password("x", "garbage")
    assert account_auth.hash_password("same") != account_auth.hash_password("same")


def test_register_logs_in_and_me(client):
    res = register(client, "Alice_01", nickname="  小爱  ")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert res.json()["user"]["email"] == "alice_01@example.com"
    assert res.json()["user"]["nickname"] == "小爱"
    cookie = res.headers["set-cookie"]
    assert "freevideo_auth=" in cookie and "HttpOnly" in cookie and "Path=/api" in cookie and "SameSite=lax" in cookie
    me = client.get("/api/auth/me").json()["user"]
    assert me["email"] == "alice_01@example.com" and "password_hash" not in me and me["created_at"].endswith("Z")


def test_default_nickname_and_guest_me(client):
    assert client.get("/api/auth/me").json() == {"user": None}
    assert register(client, "bob_99").json()["user"]["nickname"] == "bob_99"


@pytest.mark.parametrize("body,detail", [
    ({"email": "ab", "password": PASSWORD}, "邮箱"),
    ({"email": "中文@example.com", "password": PASSWORD}, "邮箱"),
    ({"email": "alice@example.com", "password": "short"}, "8–128"),
    ({"email": "alice@example.com", "password": "x" * 129}, "8–128"),
    ({"email": "alice@example.com", "password": "        "}, "空白"),
    ({"email": "alice@example.com", "password": "ALICE@EXAMPLE.COM"}, "邮箱相同"),
    ({"email": "alice@example.com", "password": PASSWORD, "nickname": "n" * 31}, "昵称"),
])
def test_register_validation(client, body, detail):
    res = client.post("/api/auth/register", json={**body, **challenge(client)})
    assert res.status_code == 422 and detail in res.json()["detail"]


def test_duplicate_username_case_insensitive(client):
    assert register(client, "alice").status_code == 200
    res = register(make_client(), "ALICE")
    assert res.status_code == 409 and res.json()["detail"] == "该邮箱已被注册"


def test_successful_registration_consumes_captcha(client):
    payload = {"email": "once@example.com", "password": PASSWORD, **challenge(client)}
    result = client.post('/api/auth/register', json=payload)
    assert result.status_code == 200
    assert result.json()['user']['email_verified'] is True
    assert client.post('/api/auth/register', json=payload).json()['code'] == 'INVALID_CAPTCHA'


def test_reserved_email_verification_gate_and_schema_idempotence(client):
    assert register(client).status_code == 200
    REAL_INIT_SCHEMA()
    REAL_INIT_SCHEMA()
    assert query('SELECT email FROM users')[0]['email'] == 'alice@example.com'
    query('UPDATE users SET email_verified=0')
    assert login(make_client()).json()['code'] == 'EMAIL_NOT_VERIFIED'


@pytest.fixture
def verification_mail(monkeypatch):
    monkeypatch.setattr(config, 'AUTH_EMAIL_VERIFICATION_REQUIRED', True)
    for name in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM'):
        monkeypatch.setattr(config, name, 'test')
    monkeypatch.setattr(config, 'PUBLIC_BASE_URL', 'http://localhost:8000')
    sent = []
    monkeypatch.setattr(email_verification, 'send_email', lambda recipient, link, **kwargs: sent.append((recipient, link)))
    return sent


def test_link_registration_and_activation(client, verification_mail):
    result = register(client)
    assert result.status_code == 200 and result.json()['verification_required']
    assert 'user' not in result.json() and 'freevideo_auth' not in client.cookies
    assert not query('SELECT * FROM sessions')
    assert not query('SELECT * FROM user_quota_periods')
    assert login(client).json()['code'] == 'EMAIL_NOT_VERIFIED'
    recipient, link = verification_mail[0]
    token = link.split('#token=')[1]
    assert recipient == 'alice@example.com'
    assert query('SELECT token_hash FROM email_verifications')[0]['token_hash'] == account_auth.token_hash(token)
    # Loading a URL is not activation; only the POST consumes it.
    assert query('SELECT email_verified FROM users')[0]['email_verified'] == 0
    result = client.post('/api/auth/verify-email', json={'token': token})
    assert result.status_code == 200 and result.json()['user']['email_verified']
    assert client.get('/api/auth/me').json()['user']['email'] == recipient
    assert client.post('/api/auth/verify-email', json={'token': token}).json()['code'] == 'INVALID_VERIFICATION_LINK'


def test_registration_captcha_but_login_and_resend_without_it(client, verification_mail):
    body = {'email': 'simple@example.com', 'password': PASSWORD}
    assert client.post('/api/auth/register', json=body).status_code == 422
    result = client.post('/api/auth/register', json={**body, **challenge(client)})
    assert result.status_code == 200 and result.json()['verification_required']
    assert query('SELECT nickname FROM users')[0]['nickname'] == 'simple'
    assert client.post('/api/auth/login', json=body).json()['code'] == 'EMAIL_NOT_VERIFIED'
    query('UPDATE email_verifications SET created_at=%s', (account_store.utcnow() - timedelta(seconds=61),))
    assert client.post('/api/auth/resend-verification', json=body).status_code == 200
    token = verification_mail[-1][1].split('#token=')[1]
    assert client.post('/api/auth/verify-email', json={'token': token}).status_code == 200
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json=body).status_code == 200


def test_resend_cooldown_old_link_and_wrong_password(client, verification_mail):
    register(client)
    old = verification_mail[0][1].split('#token=')[1]
    def resend(password=PASSWORD):
        return client.post('/api/auth/resend-verification', json={'email': 'alice@example.com', 'password': password, **challenge(client)})
    assert resend('incorrect password').status_code == 400
    assert resend().status_code == 429
    query('UPDATE email_verifications SET created_at=%s', (account_store.utcnow() - timedelta(seconds=61),))
    assert resend().status_code == 200
    assert len(verification_mail) == 2
    assert client.post('/api/auth/verify-email', json={'token': old}).status_code == 400
    token = verification_mail[-1][1].split('#token=')[1]
    assert client.post('/api/auth/verify-email', json={'token': token}).status_code == 200


def test_expired_link_and_delivery_failure(client, verification_mail, monkeypatch):
    register(client)
    token = verification_mail[0][1].split('#token=')[1]
    query('UPDATE email_verifications SET expires_at=%s,created_at=%s', (account_store.utcnow() - timedelta(seconds=1), account_store.utcnow() - timedelta(seconds=61)))
    assert client.post('/api/auth/verify-email', json={'token': token}).status_code == 400
    def fail(*args):
        raise AccountError('EMAIL_SEND_FAILED', 'failed', 503)
    monkeypatch.setattr(email_verification, 'send_email', fail)
    result = client.post('/api/auth/resend-verification', json={'email': 'alice@example.com', 'password': PASSWORD, **challenge(client)})
    assert result.status_code == 503
    assert query('SELECT email_verified FROM users')[0]['email_verified'] == 0
    assert not query('SELECT * FROM sessions')


def test_link_concurrent_activation_only_once(client, verification_mail):
    register(client)
    token = verification_mail[0][1].split('#token=')[1]
    results = []
    def attempt():
        results.append(make_client().post('/api/auth/verify-email', json={'token': token}).status_code)
    threads = [threading.Thread(target=attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1 and results.count(400) == 4
    assert len(query('SELECT * FROM sessions')) == 1


def test_verification_origin_and_missing_config(client, verification_mail, monkeypatch):
    assert client.post('/api/auth/verify-email', json={'token': 'x'*43}, headers={'origin': 'https://evil.example'}).status_code == 403
    monkeypatch.setattr(config, 'SMTP_PASSWORD', '')
    assert register(client).status_code == 503
    assert not query('SELECT * FROM users')


def test_password_recovery_and_all_devices_revoked(client, verification_mail, monkeypatch):
    monkeypatch.setattr(config, 'AUTH_EMAIL_VERIFICATION_REQUIRED', False)
    register(client)
    other = make_client()
    login(other)
    known = client.post('/api/auth/forgot-password', json={'email': 'alice@example.com'})
    unknown = client.post('/api/auth/forgot-password', json={'email': 'unknown@example.com'})
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()
    assert len(verification_mail) == 1
    token = verification_mail[0][1].split('#token=')[1]
    assert '/reset-password#' in verification_mail[0][1]
    assert client.post('/api/auth/reset-password', json={'token': token, 'password': 'short'}).status_code == 422
    assert client.post('/api/auth/reset-password', json={'token': token, 'password': 'new secure password'}).status_code == 200
    assert not query('SELECT * FROM sessions')
    assert other.get('/api/auth/me').json()['user'] is None
    assert login(make_client()).status_code == 401
    assert login(make_client(), password='new secure password').status_code == 200
    assert client.post('/api/auth/reset-password', json={'token': token, 'password': 'another secure password'}).json()['code'] == 'INVALID_RESET_LINK'


def test_reset_expiry_password_change_and_resend(client, verification_mail, monkeypatch):
    monkeypatch.setattr(config, 'AUTH_EMAIL_VERIFICATION_REQUIRED', False)
    register(client)
    client.post('/api/auth/forgot-password', json={'email':'alice@example.com'})
    token = verification_mail[-1][1].split('#token=')[1]
    assert client.post('/api/auth/forgot-password', json={'email':'alice@example.com'}).status_code == 429
    query('UPDATE password_resets SET expires_at=%s,created_at=%s', (account_store.utcnow()-timedelta(seconds=1),account_store.utcnow()-timedelta(seconds=61)))
    assert client.post('/api/auth/reset-password', json={'token':token,'password':'new password 123'}).status_code == 400
    account_auth.reset_limits()
    client.post('/api/auth/forgot-password', json={'email':'alice@example.com'})
    new = verification_mail[-1][1].split('#token=')[1]
    assert new != token
    assert client.post('/api/auth/reset-password', json={'token':token,'password':'new password 123'}).status_code == 400
    account_store.update_password(query('SELECT id FROM users')[0]['id'], account_auth.hash_password('changed password 123'))
    assert client.post('/api/auth/reset-password', json={'token':new,'password':'new password 123'}).status_code == 400


def test_pending_account_can_recover_and_verify_email(client, verification_mail):
    register(client)
    client.post('/api/auth/forgot-password', json={'email':'alice@example.com'})
    token = verification_mail[-1][1].split('#token=')[1]
    assert client.post('/api/auth/reset-password',json={'token':token,'password':'recovered password 123'}).status_code == 200
    assert query('SELECT email_verified FROM users')[0]['email_verified'] == 1
    assert not query('SELECT * FROM email_verifications')
    assert login(client,password='recovered password 123').status_code == 200


def test_reset_concurrency_and_origin(client, verification_mail, monkeypatch):
    monkeypatch.setattr(config, 'AUTH_EMAIL_VERIFICATION_REQUIRED', False)
    register(client)
    assert client.post('/api/auth/forgot-password', json={'email':'alice@example.com'},headers={'origin':'https://evil.example'}).status_code == 403
    client.post('/api/auth/forgot-password', json={'email':'alice@example.com'})
    token = verification_mail[-1][1].split('#token=')[1]
    outcomes=[]
    def attempt():
        outcomes.append(make_client().post('/api/auth/reset-password',json={'token':token,'password':'concurrent new password'}).status_code)
    threads=[threading.Thread(target=attempt) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert outcomes.count(200) == 1 and outcomes.count(400) == 3


def test_concurrent_email_registration():
    outcomes = []
    def attempt(i):
        _, session = account_auth.new_session(type('R', (), {'headers': {}, 'client': None})())
        try:
            account_store.create_user(f'email_racer_{i}', f'email_racer_{i}', 'racer', 'scrypt$x', session, email='race@example.com')
            outcomes.append('ok')
        except AccountError as e:
            outcomes.append(e.code)
    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count('ok') == 1
    assert outcomes.count('EMAIL_TAKEN') == 5


def test_concurrent_register_only_one_wins():
    results = []

    def attempt():
        _, session = account_auth.new_session(type("R", (), {"headers": {}, "client": None})())
        try:
            account_store.create_user("racer", "racer", "racer", "scrypt$x", session)
            results.append("ok")
        except AccountError as e:
            results.append(e.status)

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count(409) == 5
    assert len(query("SELECT id FROM users WHERE username_key='racer'")) == 1


def test_login_success_and_uniform_failure(client):
    register(make_client())
    wrong = login(client, password="wrong password")
    unknown = login(client, username="nobody")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "邮箱或密码错误"
    res = login(client, username="ALICE")
    assert res.status_code == 200 and res.json()["user"]["email"] == "alice@example.com"
    assert client.get("/api/auth/me").json()["user"]["email"] == "alice@example.com"


def test_login_lockout_after_failures(client):
    register(make_client())
    for _ in range(5):
        assert login(client, password="wrong password").status_code == 401
    res = login(client)
    assert res.status_code == 429 and "15 分钟" in res.json()["detail"]


def test_login_rate_limit_per_ip(client):
    for _ in range(10):
        login(client, username=f"user{_:02d}x")
    assert login(client, username="another").status_code == 429


def test_register_rate_limit(client):
    for i in range(5):
        assert register(make_client(), f"user_{i}").status_code == 200
    assert register(client, "user_x").status_code == 429


def test_logout_revokes_server_session(client):
    register(client)
    token = client.cookies.get("freevideo_auth")
    assert client.post("/api/auth/logout").json() == {"ok": True}
    assert client.get("/api/auth/me").json()["user"] is None
    stolen = make_client()
    stolen.cookies.set("freevideo_auth", token, path="/api")
    assert stolen.get("/api/auth/me").json()["user"] is None
    assert client.post("/api/auth/logout").status_code == 200
    assert query("SELECT id FROM sessions") == ()


def test_expired_session_is_rejected_and_cleared(client):
    register(client)
    query("UPDATE sessions SET expires_at = %s", (account_store.utcnow() - timedelta(seconds=1),))
    res = client.get("/api/auth/me")
    assert res.json()["user"] is None and 'freevideo_auth=""' in res.headers["set-cookie"]


def test_last_seen_is_touched_after_interval(client):
    register(client)
    old = account_store.utcnow() - timedelta(minutes=10)
    query("UPDATE sessions SET last_seen_at = %s", (old,))
    client.get("/api/auth/me")
    assert query("SELECT last_seen_at FROM sessions")[0]["last_seen_at"] > old


def test_no_plaintext_credentials_in_database(client):
    register(client)
    token = client.cookies.get("freevideo_auth")
    user = query("SELECT password_hash FROM users")[0]
    session = query("SELECT id, token_hash FROM sessions")[0]
    assert PASSWORD not in user["password_hash"] and user["password_hash"].startswith("scrypt$")
    assert session["token_hash"] == account_auth.token_hash(token) and token not in session.values()


def test_update_profile(client):
    assert client.patch("/api/account/profile", json={"nickname": "x"}).status_code == 401
    register(client)
    res = client.patch("/api/account/profile", json={"nickname": " 新昵称 "})
    assert res.json()["user"]["nickname"] == "新昵称"
    assert client.get("/api/auth/me").json()["user"]["nickname"] == "新昵称"
    assert client.patch("/api/account/profile", json={"nickname": "   "}).status_code == 422


def test_change_password_revokes_all_sessions(client):
    register(client)
    other = make_client()
    login(other)
    res = client.post("/api/account/password", json={"old_password": "bad password", "new_password": "new pass 123"})
    assert res.status_code == 400 and res.json()["detail"] == "当前密码不正确"
    same = client.post("/api/account/password", json={"old_password": PASSWORD, "new_password": PASSWORD})
    assert same.status_code == 422
    res = client.post("/api/account/password", json={"old_password": PASSWORD, "new_password": "new pass 123"})
    assert res.status_code == 200
    assert client.get("/api/auth/me").json()["user"] is None
    assert other.get("/api/auth/me").json()["user"] is None
    assert login(make_client()).status_code == 401
    assert login(make_client(), password="new pass 123").status_code == 200


def test_device_management(client):
    register(client)
    other = make_client()
    login(other)
    third = make_client()
    login(third)
    sessions = client.get("/api/account/sessions").json()["sessions"]
    assert len(sessions) == 3 and sum(s["current"] for s in sessions) == 1
    assert all(set(s) == {"id", "device", "ip", "created_at", "last_seen_at", "expires_at", "current"} for s in sessions)
    other_id = next(s["id"] for s in other.get("/api/account/sessions").json()["sessions"] if s["current"])
    assert client.delete(f"/api/account/sessions/{other_id}").json() == {"ok": True, "current": False}
    assert other.get("/api/auth/me").json()["user"] is None
    assert client.delete(f"/api/account/sessions/{other_id}").status_code == 404
    mallory = make_client()
    register(mallory, "mallory")
    my_id = next(s["id"] for s in client.get("/api/account/sessions").json()["sessions"] if s["current"])
    assert mallory.delete(f"/api/account/sessions/{my_id}").status_code == 404
    assert client.post("/api/account/sessions/revoke-others").json() == {"revoked": 1}
    assert third.get("/api/auth/me").json()["user"] is None
    assert client.get("/api/auth/me").json()["user"]["email"] == "alice@example.com"


def test_device_label():
    from app.account_api import device_label
    edge = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36 Edg/140.0"
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/604.1"
    assert device_label(edge) == "Edge · Windows"
    assert device_label(iphone) == "Safari · iOS"
    assert device_label("") == "未知浏览器 · 未知系统"


def test_delete_account(client):
    register(client)
    other = make_client()
    login(other)
    res = client.request("DELETE", "/api/account", json={"password": PASSWORD, "confirm_email": "bob@example.com"})
    assert res.status_code == 422
    res = client.request("DELETE", "/api/account", json={"password": "bad password", "confirm_email": "alice@example.com"})
    assert res.status_code == 400
    res = client.request("DELETE", "/api/account", json={"password": PASSWORD, "confirm_email": "ALICE@EXAMPLE.COM"})
    assert res.status_code == 200
    assert client.get("/api/auth/me").json()["user"] is None
    assert other.get("/api/auth/me").json()["user"] is None
    assert query("SELECT id FROM users") == () and query("SELECT id FROM sessions") == ()
    assert login(make_client()).status_code == 401
    assert register(make_client()).status_code == 200


@pytest.mark.parametrize("headers", [{"sec-fetch-site": "cross-site"}, {"origin": "https://evil.example"}])
def test_cross_site_requests_rejected(client, headers):
    assert client.post("/api/auth/register", json={"email": "alice@example.com", "password": PASSWORD, **challenge(client)},
                       headers=headers).status_code == 403
    register(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 403
    assert client.patch("/api/account/profile", json={"nickname": "x"}, headers=headers).status_code == 403
    assert client.get("/api/auth/me").json()["user"]["email"] == "alice@example.com"


def test_same_origin_requests_allowed(client):
    assert client.post("/api/auth/register", json={"email": "alice@example.com", "password": PASSWORD, **challenge(client)},
                       headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"}).status_code == 200


GATED = [
    ("post", "/api/batch", {"urls": ["https://a.com/1"]}),
    ("post", "/api/batch-transcriptions", {"urls": ["https://a.com/1"], "allow_asr": True}),
    ("get", "/api/batch-transcriptions/abc", None),
    ("get", "/api/batch-transcriptions/abc/file", None),
    ("post", "/api/learn/summary", {"url": "https://a.com/1"}),
    ("post", "/api/learn/mindmap", {"url": "https://a.com/1"}),
    ("post", "/api/learn/chat", {"url": "https://a.com/1", "messages": [{"role": "user", "content": "hi"}]}),
    ("post", "/api/ai/summary", {"url": "https://a.com/1"}),
    ("post", "/api/ai/translate", {"url": "https://a.com/1"}),
]


@pytest.mark.parametrize("method,path,body", GATED)
def test_gated_features_require_login(client, monkeypatch, method, path, body):
    from app import ai
    monkeypatch.setattr(ai, "enabled", lambda: False)
    res = client.request(method.upper(), path, json=body)
    assert res.status_code == 401 and res.json()["code"] == "AUTH_REQUIRED"
    register(client)
    # Invalid body / disabled AI after login: passes auth without starting downloads or paid calls.
    res = client.request(method.upper(), path, json={} if body else None)
    assert res.status_code in (404, 422, 503), res.text


def test_guest_features_stay_open(client, monkeypatch):
    from app import downloader
    monkeypatch.setattr(downloader, "parse", lambda url: {"title": "ok"})
    assert client.post("/api/parse", json={"url": "https://a.com/1"}).json() == {"title": "ok"}
    assert client.get("/api/jobs/missing").status_code == 404


def test_database_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setattr(config, "MYSQL_PORT", 1)
    res = login(client)
    assert res.status_code == 503 and res.json()["detail"] == "账号服务暂不可用，请稍后再试"
    assert client.post("/api/batch", json={"urls": ["https://a.com/1"]}).status_code == 401  # no cookie → guest
    client.cookies.set("freevideo_auth", "x" * 43, path="/api")
    assert client.get("/api/auth/me").status_code == 503
