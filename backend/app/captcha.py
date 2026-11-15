"""Single-process, browser-bound one-use image challenges; no answer in client payload."""
import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
import zlib
from fastapi import Request, Response
from . import account_auth as auth, config
from .errors import AccountError

COOKIE = "freevideo_captcha"
_lock = threading.Lock()
_challenges = {}
# Bitmap glyphs are rasterized server-side, never sent as SVG/text.
_GLYPHS = {
 '0': '01110100011001110101110011000101110',
 '1': '00100011000010000100001000010001110',
 '+': '00000001000010011111001000010000000',
 '-': '00000000000000011111000000000000000',
 '=': '00000000001111100000111110000000000',
 '?': '01110100010000100010001000000000100',
 '2': '01110100010000100010001000100011111',
 '3': '11110000010000101110000010000111110',
 '4': '00010001100101010010111110001000010',
 '5': '11111100001000011110000010000111110',
 '6': '01110100001000011110100011000101110',
 '7': '11111000010001000100010000100001000',
 '8': '01110100011000101110100011000101110',
 '9': '01110100011000101111000010000101110',
}


def _problem():
    left, right = secrets.randbelow(9) + 1, secrets.randbelow(9) + 1
    operator = secrets.choice('+-')
    if operator == '-':
        left, right = max(left, right), min(left, right)
    result = left + right if operator == '+' else left - right
    return f'{left}{operator}{right}=?', str(result)

def _image(answer):
    width, height = 176, 56
    pixels = bytearray([245, 247, 255] * width * height)
    def dot(x, y, rgb):
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset:offset+3] = bytes(rgb)
    for i, char in enumerate(answer):
        top = 9 + secrets.randbelow(8)
        for j, bit in enumerate(_GLYPHS[char]):
            if bit == '1':
                for dx in range(4):
                    for dy in range(4):
                        dot(10 + i * 32 + (j % 5) * 4 + dx, top + (j // 5) * 4 + dy, (55, 65, 130))
    for _ in range(180):
        dot(secrets.randbelow(width), secrets.randbelow(height), (150, 160, 200))
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    raw = b''.join(b'\x00' + pixels[y*width*3:(y+1)*width*3] for y in range(height))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')

def issue(request: Request, response: Response):
    auth.check_origin(request)
    auth.rate_limit('captcha:' + auth.peer(request), 60, 600, '验证码获取过于频繁，请稍后再试')
    browser = request.cookies.get(COOKIE, '')
    if len(browser) != 43 or not browser.isascii():
        browser = secrets.token_urlsafe(32)
    response.set_cookie(COOKIE, browser, httponly=True, secure=config.SESSION_SECURE, samesite='lax', path='/api', max_age=3600)
    expression, answer = _problem()
    challenge = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _lock:
        for key in list(_challenges):
            if _challenges[key][2] <= now:
                del _challenges[key]
        if len(_challenges) >= 2000:
            raise AccountError('CAPTCHA_BUSY', '验证码服务繁忙，请稍后重试', 503)
        _challenges[challenge] = (hashlib.sha256(browser.encode()).digest(), hashlib.sha256(answer.encode()).digest(), now + 300)
    return {'id': challenge, 'image': _image(expression), 'expires_in': 300}

def consume(request: Request, challenge: str, answer: str):
    with _lock:
        item = _challenges.pop(challenge, None)
    browser = request.cookies.get(COOKIE, '')
    if (not item or item[2] <= time.monotonic()
            or not hmac.compare_digest(item[0], hashlib.sha256(browser.encode()).digest())
            or not hmac.compare_digest(item[1], hashlib.sha256(answer.strip().encode()).digest())):
        raise AccountError('INVALID_CAPTCHA', '图形验证码错误或已过期，请刷新后重试', 400)
