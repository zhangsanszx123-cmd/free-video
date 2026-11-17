"""Login feedback and lockout, isolated from MySQL and external services."""
import pytest
from types import SimpleNamespace
from app import account_store, account_auth, config


@pytest.mark.parametrize('registered', [False, True])
def test_login_feedback_and_lockout(client, monkeypatch, registered):
    # Exercise the email lock independently of the per-IP request limit.
    monkeypatch.setattr(config, 'AUTH_LOGIN_RATE_LIMIT', 100)
    clock = [1000.0]
    monkeypatch.setattr(account_auth, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(account_store, 'get_email_credentials', lambda email: {'password_hash': 'fake'} if registered else None)
    monkeypatch.setattr(account_auth, 'verify_password', lambda *args: False)
    body = {'email': 'feedback@example.com', 'password': 'wrong password'}
    for _ in range(10):
        response = client.post('/api/auth/login', json=body)
        assert response.status_code == 401
        assert response.json()['code'] == ('INVALID_CREDENTIALS' if registered else 'EMAIL_NOT_REGISTERED')
        assert response.json()['detail'] == ('密码错误' if registered else '该邮箱尚未注册，请先注册')
    response = client.post('/api/auth/login', json=body)
    assert response.status_code == 429
    assert '15 分钟' in response.json()['detail']
    clock[0] += 899
    assert client.post('/api/auth/login', json=body).status_code == 429
    clock[0] += 2
    assert client.post('/api/auth/login', json=body).status_code == 401
