"""Test-side reader for our bitmap CAPTCHA; never used by application code."""
import ast
import base64
from pathlib import Path
import struct
import zlib

def solve(image):
    source = Path(__file__).resolve().parents[2] / 'backend/app/captcha.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    glyphs = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_GLYPHS' for t in node.targets))
    data = base64.b64decode(image.split(',')[1])
    compressed = b''
    offset = 8
    while offset < len(data):
        size = struct.unpack('!I', data[offset:offset+4])[0]
        if data[offset+4:offset+8] == b'IDAT':
            compressed += data[offset+8:offset+8+size]
        offset += size + 12
    raw = zlib.decompress(compressed)
    def dark(x, y):
        pos = y * (176 * 3 + 1) + 1 + x * 3
        return raw[pos:pos+3] == bytes((55, 65, 130))
    answer = ''
    for i in range(5):
        candidates = []
        for char, pattern in glyphs.items():
            for top in range(9, 17):
                score = sum((sum(dark(10+i*32+(j%5)*4+dx, top+(j//5)*4+dy) for dx in range(4) for dy in range(4)) >= 10) == (bit == '1') for j, bit in enumerate(pattern))
                candidates.append((score, char))
        answer += max(candidates)[1]
    left, operator, right = int(answer[0]), answer[1], int(answer[2])
    return str(left + right if operator == '+' else left - right)

def captcha_payload(page, base):
    data = page.request.get(base + '/api/auth/captcha').json()
    return dict(captcha_id=data['id'], captcha_answer=solve(data['image']))

def fill_captcha(scope):
    if scope.get_by_label('图形验证码', exact=True).count() == 0:
        return
    image = scope.locator('img[alt^="算术验证码"]')
    image.wait_for(state='visible')
    scope.get_by_label('图形验证码', exact=True).fill(solve(image.get_attribute('src')))
