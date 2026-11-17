"""Mock email sending on built :8000 frontend; advance browser time without waiting."""
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        page = browser.new_page(viewport={'width': width, 'height': 844})
        page.clock.install()
        calls, errors = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def api(route):
            path = route.request.url.split('/api/')[1].split('?')[0]
            if path == 'auth/me':
                return route.fulfill(json={'user': None})
            if path == 'auth/captcha':
                return route.fulfill(json={'id': 'test', 'image': 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>'})
            if path in ('auth/register', 'auth/resend-verification'):
                calls.append(path)
                return route.fulfill(json={'verification_required': True, 'resend_after': 60})
            if path == 'auth/login':
                return route.fulfill(status=403, json={'code': 'EMAIL_NOT_VERIFIED', 'detail': '请先完成邮箱验证后再登录'})
            return route.fulfill(json={'ok': True, 'plans': []})

        page.route('**/api/**', api)
        page.goto('http://127.0.0.1:8000/register')
        page.get_by_label('邮箱', exact=True).fill('cooldown@example.com')
        page.get_by_label('密码', exact=True).fill('password 2026')
        page.get_by_label('图形验证码', exact=True).fill('2')
        page.get_by_role('button', name='注册账号', exact=True).click()
        button = page.get_by_role('button', name='60 秒后可重新发送', exact=True)
        expect(button).to_be_disabled()
        # Enter submits the form too; the handler must prevent duplicate sends.
        page.get_by_label('密码', exact=True).press('Enter')
        assert calls == ['auth/register']
        page.clock.fast_forward(59000)
        expect(page.get_by_role('button', name='1 秒后可重新发送', exact=True)).to_be_disabled()
        page.clock.fast_forward(1000)
        page.get_by_role('button', name='重新发送验证邮件', exact=True).click()
        expect(page.get_by_role('button', name='60 秒后可重新发送', exact=True)).to_be_disabled()
        assert calls == ['auth/register', 'auth/resend-verification']
        # Switching to the login component must retain this email's cooldown.
        page.get_by_role('button', name='直接登录', exact=True).click()
        page.wait_for_url('**/login')
        expect(page.locator('main').get_by_role('heading', name='欢迎回来', exact=True)).to_be_visible()
        page.get_by_label('邮箱', exact=True).fill('cooldown@example.com')
        page.get_by_label('密码', exact=True).fill('password 2026')
        page.locator('main').get_by_role('button', name='登录', exact=True).click()
        expect(page.get_by_role('button', name='60 秒后可重新发送', exact=True)).to_be_disabled()
        page.clock.fast_forward(60000)
        page.get_by_role('button', name='重新发送验证邮件', exact=True).click()
        expect(page.get_by_role('button', name='60 秒后可重新发送', exact=True)).to_be_disabled()
        assert len(calls) == 3
        assert not errors, errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.close()
        print(f'PASS verification cooldown at {width}px')
    browser.close()
