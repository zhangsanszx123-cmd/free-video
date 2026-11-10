"""Account API tests against a real, dedicated MySQL test database (MYSQL_TEST_DATABASE)."""
import threading
from datetime import timedelta

import pymysql
import pytest
from fastapi.testclient import TestClient

from app import account_auth, account_store, config, main
from app.errors import AccountError

MAIN_DATABASE = config.MYSQL_DATABASE
REAL_INIT_SCHEMA = account_store.init_schema
PASSWORD = "correct horse 9"

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason="MYSQL_TEST_DATABASE not configured")


@pytest.fixture(autouse=True)
def db(monkeypatch):
    assert config.MYSQL_TEST_DATABASE != MAIN_DATABASE, "MYSQL_TEST_DATABASE must differ from MYSQL_DATABASE"
    monkeypatch.setattr(config, "AUTH_REGISTER_RATE_LIMIT", 5)
    monkeypatch.setattr(config, "AUTH_LOGIN_RATE_LIMIT", 10)
    main.app.dependency_overrides.pop(account_auth.require_user, None)
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
    return client.post("/api/auth/register", json={"username": username, "password": password, **extra})


def login(client, username="alice", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


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
    assert res.json()["user"]["username"] == "Alice_01"
    assert res.json()["user"]["nickname"] == "小爱"
    cookie = res.headers["set-cookie"]
    assert "freevideo_auth=" in cookie and "HttpOnly" in cookie and "Path=/api" in cookie and "SameSite=lax" in cookie
    me = client.get("/api/auth/me").json()["user"]
    assert me["username"] == "Alice_01" and "password_hash" not in me and me["created_at"].endswith("Z")


def test_default_nickname_and_guest_me(client):
    assert client.get("/api/auth/me").json() == {"user": None}
    assert register(client, "bob_99").json()["user"]["nickname"] == "bob_99"


@pytest.mark.parametrize("body,detail", [
    ({"username": "ab", "password": PASSWORD}, "用户名"),
    ({"username": "中文用户名", "password": PASSWORD}, "用户名"),
    ({"username": "alice", "password": "short"}, "8–128"),
    ({"username": "alice", "password": "x" * 129}, "8–128"),
    ({"username": "alice", "password": "        "}, "空白"),
    ({"username": "alice1234", "password": "ALICE1234"}, "用户名相同"),
    ({"username": "alice", "password": PASSWORD, "nickname": "n" * 31}, "昵称"),
])
def test_register_validation(client, body, detail):
    res = client.post("/api/auth/register", json=body)
    assert res.status_code == 422 and detail in res.json()["detail"]


def test_duplicate_username_case_insensitive(client):
    assert register(client, "alice").status_code == 200
    res = register(make_client(), "ALICE")
    assert res.status_code == 409 and res.json()["detail"] == "该用户名已被注册"


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
    assert wrong.json()["detail"] == unknown.json()["detail"] == "用户名或密码错误"
    res = login(client, username="ALICE")
    assert res.status_code == 200 and res.json()["user"]["username"] == "alice"
    assert client.get("/api/auth/me").json()["user"]["username"] == "alice"


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
    assert client.get("/api/auth/me").json()["user"]["username"] == "alice"


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
    res = client.request("DELETE", "/api/account", json={"password": PASSWORD, "confirm_username": "bob"})
    assert res.status_code == 422
    res = client.request("DELETE", "/api/account", json={"password": "bad password", "confirm_username": "alice"})
    assert res.status_code == 400
    res = client.request("DELETE", "/api/account", json={"password": PASSWORD, "confirm_username": "ALICE"})
    assert res.status_code == 200
    assert client.get("/api/auth/me").json()["user"] is None
    assert other.get("/api/auth/me").json()["user"] is None
    assert query("SELECT id FROM users") == () and query("SELECT id FROM sessions") == ()
    assert login(make_client()).status_code == 401
    assert register(make_client()).status_code == 200


@pytest.mark.parametrize("headers", [{"sec-fetch-site": "cross-site"}, {"origin": "https://evil.example"}])
def test_cross_site_requests_rejected(client, headers):
    assert client.post("/api/auth/register", json={"username": "alice", "password": PASSWORD},
                       headers=headers).status_code == 403
    register(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 403
    assert client.patch("/api/account/profile", json={"nickname": "x"}, headers=headers).status_code == 403
    assert client.get("/api/auth/me").json()["user"]["username"] == "alice"


def test_same_origin_requests_allowed(client):
    assert client.post("/api/auth/register", json={"username": "alice", "password": PASSWORD},
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
