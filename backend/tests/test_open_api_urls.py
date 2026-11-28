"""Offline URL-boundary tests, no DNS or platform access."""
import socket
import pytest
import httpx
from app import open_api_auth
from app.errors import AccountError


@pytest.mark.parametrize('url', ['http://localhost/video', 'http://169.254.169.254/latest/meta-data',
    'https://www.douyin.com.evil.example/video/7420000000000000000',
    'https://user:pass@www.douyin.com/video/7420000000000000000',
    'https://www.douyin.com:8000/video/7420000000000000000',
    'https://www.douyin.com/video/7420000000000000000#fragment',
    'https://www.youtube.com/redirect?q=http://127.0.0.1', 'https://www.bilibili.com/list/123'])
def test_reject_arbitrary_urls(monkeypatch, url):
    monkeypatch.setattr(open_api_auth, '_public_dns', lambda host: None)
    with pytest.raises(AccountError):
        open_api_auth.video_url(url)


def test_dns_private_and_all_addresses_checked(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('8.8.8.8', 443)), (None, None, None, None, ('127.0.0.1', 443))])
    with pytest.raises(AccountError, match='不可访问'):
        open_api_auth.video_url('https://www.douyin.com/video/7420000000000000000')


def test_share_redirect_revalidates_target(monkeypatch):
    monkeypatch.setattr(open_api_auth, '_public_dns', lambda host: None)
    calls = []
    def get(self, url):
        calls.append(url)
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    monkeypatch.setattr(httpx.Client, 'get', get)
    with pytest.raises(AccountError):
        open_api_auth.video_url('https://v.douyin.com/abc/')
    assert calls == ['https://v.douyin.com/abc/']


@pytest.mark.parametrize('url,canonical', [
    ('分享 https://www.bilibili.com/video/BV1234567890?p=2&url=http://localhost', 'https://www.bilibili.com/video/BV1234567890?p=2'),
    ('https://youtu.be/abcdefghijk?si=tracking', 'https://www.youtube.com/watch?v=abcdefghijk'),
    ('https://www.douyin.com/video/7420000000000000000?modal_id=123', 'https://www.douyin.com/video/7420000000000000000'),
])
def test_only_id_and_selected_page_reach_extractor(monkeypatch, url, canonical):
    monkeypatch.setattr(open_api_auth, '_public_dns', lambda host: None)
    assert open_api_auth.video_url(url) == canonical
