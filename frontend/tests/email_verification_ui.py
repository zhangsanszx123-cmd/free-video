"""Mocked email-link registration UI. Requires Vite :5178; no mail sent."""
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[2]
image = subprocess.check_output([str(root/'backend/.venv/Scripts/python.exe'), '-c', "from app.captcha import _image; print(_image('6-4=?'))"], cwd=root/'backend', text=True).strip()
shots = root/'.runtime/email-verification-ui'
shots.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        page = browser.new_page(viewport=dict(width=width, height=1000))
        errors, verified = [], []
        state = dict(user=None)
        page.on('pageerror', lambda e: errors.append(str(e)))
        def api(route):
            path = route.request.url.split('/api/')[1].split('?')[0]
            if path == 'auth/me':
                return route.fulfill(json=dict(user=state['user']))
            if path == 'auth/captcha':
                return route.fulfill(json=dict(id='test', image=image, expires_in=300))
            if path in ('auth/register', 'auth/resend-verification'):
                assert route.request.post_data_json['email'] == 'test@example.com'
                return route.fulfill(json=dict(verification_required=True, email='test@example.com', resend_after=60))
            if path == 'auth/verify-email':
                verified.append(route.request.post_data_json)
                state['user'] = dict(id=2, username='u_test', email='test@example.com', nickname='test', email_verified=True, created_at='2026-11-15T00:00:00Z')
                return route.fulfill(json=dict(user=state['user']))
            return route.fulfill(json=dict(ok=True, plans=[]))
        page.route('**/api/**', api)
        page.goto('http://127.0.0.1:5178/register')
        page.get_by_label('邮箱', exact=True).fill('test@example.com')
        page.get_by_label('密码', exact=True).fill('password 2026')
        expect(page.get_by_label('图形验证码', exact=True)).to_be_visible()
        page.get_by_label('图形验证码', exact=True).fill('2')
        page.get_by_role('button', name='注册账号', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='验证邮件已发送')).to_be_visible()
        assert page.url.endswith('/register') and state['user'] is None
        page.screenshot(path=str(shots/f'pending-{width}.png'), full_page=True)
        # Opening the email URL must not consume its token automatically.
        page.goto('http://127.0.0.1:5178/verify-email#token=' + 't'*43)
        expect(page.get_by_role('button', name='确认验证并登录')).to_be_visible()
        assert '#token=' not in page.url and not verified
        page.get_by_role('button', name='确认验证并登录').click()
        expect(page.get_by_role('status').filter(has_text='邮箱验证成功')).to_be_visible()
        assert verified == [dict(token='t'*43)]
        page.screenshot(path=str(shots/f'verified-{width}.png'), full_page=True)
        assert not errors, errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.close()
        print(f'PASS email verification at {width}px')
    # Switching an already logged-in identity must preserve the confirmation result.
    page = browser.new_page()
    state = dict(user=dict(id=1, username='old', nickname='old', email='old@example.com', created_at='2026-11-15T00:00:00Z'))
    page.route('**/api/**', api)
    page.goto('http://127.0.0.1:5178/verify-email#token='+'t'*43)
    page.get_by_role('button', name='确认验证并登录').click()
    expect(page.get_by_role('status').filter(has_text='邮箱验证成功')).to_be_visible()
    page.close()
    browser.close()
