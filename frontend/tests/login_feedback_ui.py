"""Run against built frontend on :8000; all API responses are mocked."""
from playwright.sync_api import sync_playwright, expect


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        for modal in (True, False):
            page = browser.new_page(viewport={'width': width, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def api(route):
                path = route.request.url.split('/api/')[1].split('?')[0]
                if path == 'auth/me':
                    return route.fulfill(json={'user': None})
                if path == 'auth/login':
                    registered = route.request.post_data_json['email'] == 'known@example.com'
                    return route.fulfill(status=401, json={
                        'code': 'INVALID_CREDENTIALS' if registered else 'EMAIL_NOT_REGISTERED',
                        'detail': '密码错误' if registered else '该邮箱尚未注册，请先注册'})
                if path == 'auth/captcha':
                    return route.fulfill(json={'id': 'test', 'image': 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>'})
                return route.fulfill(json={'ok': True, 'plans': []})

            page.route('**/api/**', api)
            page.goto('http://127.0.0.1:8000/' if modal else 'http://127.0.0.1:8000/login?redirect=/history')
            if modal:
                if width == 390:
                    page.get_by_role('button', name='打开导航菜单').click()
                page.locator('nav').get_by_role('button', name='登录', exact=True).click()
            form = page.locator('dialog[open]') if modal else page.locator('main')
            form.get_by_label('邮箱', exact=True).fill('known@example.com')
            form.get_by_label('密码', exact=True).fill('wrong password')
            form.get_by_role('button', name='登录', exact=True).click()
            expect(form.get_by_role('alert')).to_contain_text('密码错误')
            expect(form.get_by_role('button', name='立即注册')).to_have_count(0)
            form.get_by_label('邮箱', exact=True).fill('missing@example.com')
            form.get_by_role('button', name='登录', exact=True).click()
            expect(form.get_by_role('alert')).to_contain_text('该邮箱尚未注册')
            form.get_by_role('button', name='立即注册', exact=True).click()
            expect(form.get_by_label('邮箱', exact=True)).to_have_value('missing@example.com')
            expect(form.get_by_label('密码', exact=True)).to_have_value('')
            expect(form.get_by_label('图形验证码', exact=True)).to_be_visible()
            if modal:
                expect(form.get_by_role('tab', name='注册', exact=True)).to_have_attribute('aria-selected', 'true')
            else:
                assert 'redirect=/history' in page.url or 'redirect=%2Fhistory' in page.url
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            page.close()
            print(f'PASS login feedback width={width}, modal={modal}')
    browser.close()
