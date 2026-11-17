"""Password recovery UI, all API traffic mocked; Vite on :5178."""
from pathlib import Path
import os
from playwright.sync_api import sync_playwright, expect

shots=Path('.runtime/password-recovery-ui')
shots.mkdir(parents=True,exist_ok=True)
BASE = os.environ.get('UI_BASE_URL', 'http://127.0.0.1:5178')
with sync_playwright() as pw:
    browser=pw.chromium.launch()
    for width in (1440,390):
        page=browser.new_page(viewport=dict(width=width,height=844))
        page.clock.install()
        errors,requests=[],[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def api(route):
            path=route.request.url.split('/api/')[1].split('?')[0]
            if path=='auth/me': return route.fulfill(json={'user':None})
            if path=='auth/forgot-password':
                requests.append(route.request.post_data_json)
                return route.fulfill(json={'ok':True})
            if path=='auth/reset-password':
                requests.append(route.request.post_data_json)
                return route.fulfill(json={'ok':True})
            return route.fulfill(json={'ok':True,'plans':[]})
        page.route('**/api/**',api)
        page.goto(BASE + '/')
        page.locator('nav').get_by_role('button',name='登录',exact=True,include_hidden=True).first.evaluate('el=>el.click()')
        page.get_by_role('button',name='忘记密码？').click()
        dialog=page.locator('dialog[open]')
        expect(dialog.get_by_role('tab',name='找回密码',exact=True)).to_have_attribute('aria-selected','true')
        assert page.url==BASE + '/'
        assert dialog.get_by_role('tab').all_text_contents()==['登录','注册','找回密码']
        page.get_by_label('注册邮箱').fill('bad')
        page.get_by_role('button',name='发送重置邮件',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('邮箱')
        assert not requests
        page.get_by_label('注册邮箱').fill('test@example.com')
        page.get_by_role('button',name='发送重置邮件',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='如果该邮箱已注册')).to_be_visible()
        expect(dialog.get_by_role('button',name='返回登录',exact=True)).to_have_count(0)
        expect(dialog.get_by_role('button',name='60 秒后可重新发送',exact=True)).to_be_disabled()
        page.get_by_label('注册邮箱').press('Enter')
        assert len(requests)==1
        page.clock.fast_forward(59000)
        expect(dialog.get_by_role('button',name='1 秒后可重新发送',exact=True)).to_be_disabled()
        page.clock.fast_forward(1000)
        dialog.get_by_role('button',name='重新发送重置邮件',exact=True).click()
        expect(dialog.get_by_role('button',name='60 秒后可重新发送',exact=True)).to_be_disabled()
        assert len(requests)==2
        page.screenshot(path=str(shots/f'forgot-{width}.png'),full_page=True)
        dialog.get_by_role('tab',name='登录',exact=True).click()
        expect(dialog.get_by_role('tab',name='登录',exact=True)).to_have_attribute('aria-selected','true')
        page.goto(BASE + '/reset-password#token='+'t'*43)
        expect(page.get_by_label('新密码')).to_be_visible()
        assert '#token' not in page.url
        assert len(requests)==2
        page.get_by_label('新密码').fill('new password 2026')
        page.get_by_role('button',name='重置密码',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='密码已重置')).to_be_visible()
        assert requests[-1]=={'token':'t'*43,'password':'new password 2026'}
        page.screenshot(path=str(shots/f'reset-{width}.png'),full_page=True)
        assert not errors,errors
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.goto(BASE + '/reset-password')
        expect(page.get_by_role('alert')).to_contain_text('缺少凭证')
        expect(page.get_by_role('button',name='重置密码',exact=True)).to_be_disabled()
        page.goto(BASE + '/forgot-password')
        expect(page.get_by_role('button',name='返回登录',exact=True)).to_have_count(0)
        page.get_by_label('注册邮箱').fill('backup@example.com')
        page.get_by_role('button',name='发送重置邮件',exact=True).click()
        expect(page.get_by_role('button',name='60 秒后可重新发送',exact=True)).to_be_disabled()
        page.close()
        print(f'PASS password recovery at {width}px')
    browser.close()
