"""Bearer-only authentication and a deliberately narrow public-video URL boundary."""
import hashlib
import ipaddress
import re
import socket
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import account_auth, downloader, open_api_store
from .errors import AccountError

bearer = HTTPBearer(auto_error=False, scheme_name='DeveloperKey')
HOSTS = {'douyin.com', 'www.douyin.com', 'v.douyin.com', 'iesdouyin.com', 'www.iesdouyin.com',
         'bilibili.com', 'www.bilibili.com', 'm.bilibili.com', 'b23.tv',
         'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}


def require_key(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    account_auth.rate_limit('open-auth:' + account_auth.peer(request), 180, 60)
    token = credentials.credentials if credentials else ''
    if not re.fullmatch(r'fv_live_[A-Za-z0-9_-]{43}', token):
        raise AccountError('API_KEY_INVALID', '请在 Authorization: Bearer 请求头中提供有效 API 密钥', 401)
    return open_api_store.authenticate(hashlib.sha256(token.encode()).hexdigest())


def public_host(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ('http', 'https') or parts.hostname not in HOSTS or parts.username or parts.password
                or parts.port not in (None, 80, 443) or parts.fragment or '\\' in url or any(ord(c) <= 32 for c in url)):
            raise ValueError()
    except ValueError:
        raise AccountError('UNSUPPORTED_URL', '首版仅支持抖音、B站、YouTube 的公开作品链接', 422) from None
    return parts


def _public_dns(host):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise AccountError('UNSAFE_URL', '视频链接解析到了不可访问的地址', 422)
    except OSError:
        raise AccountError('URL_UNAVAILABLE', '暂时无法解析视频域名，请稍后重试', 503) from None


def video_url(text):
    """Expand only known share hosts; validate EVERY hop, discard unrelated query options.

    No generic URL extractor is exposed: accepted final paths contain only video IDs.
    The domain allowlist is fixed (callers cannot control DNS authority).
    """
    url = downloader.extract_url(text)
    for _ in range(6):
        p = public_host(url)
        _public_dns(p.hostname)
        if p.hostname not in ('v.douyin.com', 'b23.tv'):
            break
        if not re.fullmatch(r'/[A-Za-z0-9_-]+/?', p.path):
            raise AccountError('UNSUPPORTED_URL', '请输入作品分享短链接', 422)
        try:
            with httpx.Client(follow_redirects=False, timeout=10, trust_env=False) as client:
                response = client.get('https://' + p.hostname + p.path)
            if response.status_code not in (301, 302, 303, 307, 308) or not response.headers.get('location'):
                raise AccountError('URL_UNAVAILABLE', '分享短链未返回有效作品地址', 422)
            url = urljoin(url, response.headers['location'])
        except httpx.HTTPError:
            raise AccountError('URL_UNAVAILABLE', '分享链接暂时无法访问，请稍后重试', 503) from None
    else:
        raise AccountError('UNSUPPORTED_URL', '分享链接跳转次数过多', 422)
    q = parse_qs(p.query)
    if p.hostname.endswith('douyin.com') or p.hostname.endswith('iesdouyin.com'):
        match = re.fullmatch(r'/(?:video|share/video)/(\d+)/?', p.path)
        vid = match[1] if match else (q.get('modal_id') or [''])[0]
        if re.fullmatch(r'\d{10,30}', vid):
            return 'https://www.douyin.com/video/' + vid
    if p.hostname.endswith('bilibili.com'):
        match = re.fullmatch(r'/video/(BV[A-Za-z0-9]+|av\d+)/?', p.path)
        if match:
            page = (q.get('p') or ['1'])[0]
            if not page.isascii() or not page.isdigit() or not 1 <= int(page) <= 10000:
                raise AccountError('INVALID_PAGE', 'B站分 P 需为 1–10000 的整数', 422)
            return 'https://www.bilibili.com/video/' + match[1] + ('?p=' + str(int(page)) if int(page) != 1 else '')
    if p.hostname in ('youtu.be', 'youtube.com', 'www.youtube.com', 'm.youtube.com'):
        vid = p.path.strip('/') if p.hostname == 'youtu.be' else (q.get('v') or [''])[0] if p.path == '/watch' else p.path.removeprefix('/shorts/').removeprefix('/embed/').strip('/')
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            return 'https://www.youtube.com/watch?v=' + vid
    raise AccountError('UNSUPPORTED_URL', '请输入公开视频详情页，暂不支持合集、直播或图文', 422)
