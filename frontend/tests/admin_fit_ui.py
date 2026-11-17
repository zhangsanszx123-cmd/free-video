"""Admin pages must fit one viewport (no page/main scrolling) with 10 rows. Vite on :5178, API mocked.

Run: python -P frontend/tests/admin_fit_ui.py
"""
import os
import sys
from copy import deepcopy
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = os.getenv('FREEVIDEO_UI_BASE', 'http://127.0.0.1:5178')
SHOTS = Path(__file__).resolve().parents[2] / '.runtime' / 'admin-ui'
ADMIN = dict(id=1, username='owner', nickname='管理员', role='superadmin', status='active', created_at='2026-11-16T02:00:00Z')
PLANS = [dict(code=c, name=n, monthly_seconds=s, revision=1, price_cents=p, months=m, ai_monthly_limit=a, chat_daily_limit=d,
              batch_max_links=b, asr_max_minutes=x)
         for c, n, s, p, m, a, d, b, x in [('free', '免费用户', 1800, 0, 0, 10, 1, 3, 8), ('monthly', '月卡会员', 36000, 1990, 1, 300, 10, 10, 30),
                                           ('yearly', '年卡会员', 108000, 9900, 12, 500, 20, 15, 60)]]
USERS = [dict(id=i, email=f'member{i:02}@example.com', nickname=f'学习用户 {i}', email_verified=i % 2 == 1, status='active',
              created_at='2026-11-15T04:10:00Z', disabled_at=None, disabled_reason=None,
              membership=dict(plan='free', name='免费版', expires_at=None)) for i in range(1, 11)]
STAFF = [dict(ADMIN, id=i, username=f'staff{i}', nickname=f'运营 {i}', role='admin' if i > 1 else 'superadmin') for i in range(1, 11)]
HIST = [dict(id=str(i), user_id=100, user_email=f'member{i}@example.com', title=f'知识视频 {i:02}', platform='B站', status='done',
             duration_seconds=120, url='https://example.com/v', created_at='2026-11-17T02:00:00Z',
             payload={'result': {'text': '文稿', 'source': 'platform_subtitle'}}) for i in range(1, 11)]

def api(route):
    path = route.request.url.split('/api/')[1].split('?')[0]
    if path == 'admin/auth/me': return route.fulfill(json={'admin': ADMIN})
    if path == 'auth/me': return route.fulfill(json={'user': None}, status=401)
    if path == 'admin/users': return route.fulfill(json=dict(items=USERS, total=10, page=1, page_size=20))
    if path == 'admin/staff': return route.fulfill(json=dict(items=STAFF, total=10, page=1, page_size=20))
    if path == 'admin/history': return route.fulfill(json=dict(items=HIST, total=10, page=1))
    if path == 'admin/plans': return route.fulfill(json={'plans': [p for p in deepcopy(PLANS) if p['code'] != 'free']})
    if path == 'admin/plan-limits': return route.fulfill(json={'plans': deepcopy(PLANS), 'ceilings': dict(batch_max_links=20, asr_max_minutes=60)})
    return route.fulfill(json={'plans': deepcopy(PLANS), 'items': [], 'total': 0})

failed = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    SHOTS.mkdir(parents=True, exist_ok=True)
    for width, height in ((1440, 860), (1920, 900)):
        ctx = browser.new_context(viewport=dict(width=width, height=height))
        ctx.route('**/api/**', api)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        for name in ('users', 'staff', 'history', 'limits', 'pricing'):
            page.goto(f'{BASE}/admin/{name}')
            page.locator('main h1').wait_for()
            page.wait_for_timeout(400)
            m = page.evaluate("""() => { const el = document.querySelector('main.admin-scroll');
                return { doc: document.documentElement.scrollHeight - innerHeight, main: el.scrollHeight - el.clientHeight, rows: document.querySelectorAll('tbody tr').length } }""")
            ok = m['doc'] <= 0 and m['main'] <= 0
            print(('PASS' if ok else 'FAIL'), name, f'{width}x{height}', m)
            if not ok: failed.append((name, width, m))
            page.screenshot(path=str(SHOTS / f'fit-{name}-{width}.png'))
        if errors: failed.append(('pageerror', errors))
        ctx.close()
    browser.close()
for item in failed: print('FAILED', item)
sys.exit(1 if failed else 0)
