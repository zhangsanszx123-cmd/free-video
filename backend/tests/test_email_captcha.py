"""Challenge security without external mail or database dependencies."""
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app import captcha, main, account_auth, config
from app.errors import AccountError


def issue(client):
    with patch.object(captcha, '_problem', return_value=('6-4=?', '2')):
        response = client.get('/api/auth/captcha')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    result = response.json()
    assert result['image'].startswith('data:image/png;base64,')
    assert 'answer' not in result
    return dict(captcha_id=result['id'], captcha_answer='2')


def test_missing_and_wrong_captcha_cannot_register(client):
    body = dict(email='a@example.com', password='secure pass 99')
    assert client.post('/api/auth/register', json=body).status_code == 422
    challenge = issue(client)
    wrong = {**body, **challenge, 'captcha_answer': 'wrong'}
    assert client.post('/api/auth/register', json=wrong).json()['code'] == 'INVALID_CAPTCHA'
    assert client.post('/api/auth/register', json={**body, **challenge}).json()['code'] == 'INVALID_CAPTCHA'


def test_challenge_browser_binding_and_expiry(client):
    body = dict(email='a@example.com', password='secure pass 99')
    challenge = issue(client)
    other = TestClient(main.app)
    assert other.post('/api/auth/register', json={**body, **challenge}).json()['code'] == 'INVALID_CAPTCHA'
    challenge = issue(client)
    with captcha._lock:
        old = captcha._challenges[challenge['captcha_id']]
        captcha._challenges[challenge['captcha_id']] = (*old[:2], 0)
    assert client.post('/api/auth/register', json={**body, **challenge}).json()['code'] == 'INVALID_CAPTCHA'


def test_captcha_issuance_rate_and_origin(client):
    assert client.get('/api/auth/captcha', headers={'origin': 'https://evil.example'}).status_code == 403
    for _ in range(60):
        assert client.get('/api/auth/captcha').status_code == 200
    assert client.get('/api/auth/captcha').status_code == 429


@pytest.mark.parametrize('email', ['x', 'a@localhost', 'a..b@example.com', '.a@example.com', 'a@-bad.com', 'a@a..com', 'a b@example.com', '中@example.com', 'a@exam_ple.com'])
def test_invalid_email(email):
    with pytest.raises(AccountError):
        account_auth.normalize_email(email)


def test_email_normalization():
    assert account_auth.normalize_email(' A+b@Example.COM ') == 'a+b@example.com'


@pytest.mark.parametrize('operator,number,expected', [('+', 8, '18'), ('-', 0, '0')])
def test_arithmetic_problem_limits(monkeypatch, operator, number, expected):
    monkeypatch.setattr(captcha.secrets, 'choice', lambda _: operator)
    monkeypatch.setattr(captcha.secrets, 'randbelow', lambda _: number)
    expression, answer = captcha._problem()
    assert answer == expected
    assert expression.endswith('=?')
    assert all(len(glyph) == 35 for glyph in captcha._GLYPHS.values())
