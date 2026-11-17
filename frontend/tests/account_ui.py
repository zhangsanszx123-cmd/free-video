"""End-to-end account flows against a REAL backend + MySQL test database (no mocks for /api/auth or /api/account).

1. cd frontend && npm run build
2. Start the backend on the test database with AI/ASR disabled and relaxed limits, e.g. (bash):
   cd backend && MYSQL_DATABASE=freevideo_test DEEPSEEK_API_KEY= DASHSCOPE_API_KEY= \
     AUTH_EMAIL_VERIFICATION_REQUIRED=false AUTH_REGISTER_RATE_LIMIT=100 AUTH_LOGIN_RATE_LIMIT=100 .venv/Scripts/python -m uvicorn app.main:app --port 8010
3. python -P frontend/tests/account_ui.py      (ACCOUNT_UI_BASE overrides http://127.0.0.1:8010)
Screenshots go to .runtime/account-ui/. Each test registers a fresh random user. Video parsing is mocked.
"""
import os
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_helpers import captcha_payload, fill_captcha
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.getenv('ACCOUNT_UI_BASE', 'http://127.0.0.1:8010')
SHOTS = Path(__file__).resolve().parents[2] / '.runtime' / 'account-ui'
PASSWORD = 'E2e pass 2026'
INFO = dict(url='https://www.bilibili.com/video/BV1mAAmzqEfP', title='账号测试视频', platform='BiliBili',
            qualities=[dict(height=720, label='720P')], subtitles=[], duration=60)


def new_username():
    return 'e2e_' + secrets.token_hex(4) + '@example.com'


class AccountUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.errors = []
        self.contexts = []

    def tearDown(self):
        for ctx in self.contexts:
            ctx.close()
        self.assertEqual(self.errors, [])

    def new_page(self, width=1440, height=1000, context=None):
        if context is None:
            context = self.browser.new_context(viewport=dict(width=width, height=height))
            self.contexts.append(context)
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        return page

    @staticmethod
    def dialog(page):
        return page.locator('dialog[aria-labelledby="auth-title"]')

    def api_register(self, page, username, nickname=None):
        res = page.request.post(BASE + '/api/auth/register', data=dict(email=username, password=PASSWORD, nickname=nickname or username, **captcha_payload(page, BASE)))
        self.assertTrue(res.ok, res.text())

    def dialog_login(self, page, username, password=PASSWORD):
        d = self.dialog(page)
        d.get_by_label('邮箱').fill(username)
        d.get_by_label('密码', exact=True).fill(password)
        fill_captcha(d)
        d.get_by_role('button', name='登录', exact=True).click()

    def dialog_register(self, page, username, nickname='', password=PASSWORD, confirm=None):
        d = self.dialog(page)
        d.get_by_label('邮箱').fill(username)
        d.get_by_label('密码', exact=True).fill(password)
        fill_captcha(d)
        d.get_by_role('button', name='注册账号').click()

    def me(self, page):
        return page.request.get(BASE + '/api/auth/me').json()['user']

    def test_guest_dialog_register_and_return(self):
        page = self.new_page()
        page.goto(BASE + '/')
        page.route('**/api/batch', lambda r: r.fulfill(status=400, json=dict(detail='测试：登录后已继续提交')))
        page.locator('nav').get_by_role('link', name='批量提取').click()
        # Guests may open the page; the dialog only appears when they really start something.
        page.wait_for_url(BASE + '/batch')
        d = self.dialog(page)
        expect(d).to_be_hidden()
        page.get_by_label('下载格式').select_option('video')
        page.get_by_role('textbox').fill(INFO['url'])
        page.get_by_role('button', name='开始批量下载（1 条）').click()
        expect(d).to_be_visible()
        expect(d.get_by_role('status').filter(has_text='登录后即可使用批量提取')).to_be_visible()
        self.assertEqual(page.url, BASE + '/batch')
        expect(d.get_by_label('邮箱')).to_be_focused()
        page.screenshot(path=SHOTS / 'dialog-login-desktop.png')
        d.get_by_role('tab', name='注册').click()
        username = new_username()
        page.screenshot(path=SHOTS / 'dialog-register-desktop.png')
        fill_captcha(d)
        self.dialog_register(page, username)
        expect(d).to_be_hidden()
        self.assertEqual(page.url, BASE + '/batch')
        expect(page.get_by_role('button', name=username.split('@')[0])).to_be_visible()
        expect(page.get_by_text('测试：登录后已继续提交')).to_be_visible()  # the click resumed after login
        page.reload()
        expect(page).to_have_url(BASE + '/batch')
        # first load of a protected URL as guest: home + dialog; closing keeps the user on home
        guest = self.new_page()
        guest.goto(BASE + '/account')
        guest.wait_for_url(BASE + '/')
        gd = self.dialog(guest)
        expect(gd).to_be_visible()
        guest.keyboard.press('Escape')
        expect(gd).to_be_hidden()
        guest.locator('nav').get_by_role('button', name='登录', exact=True).click()
        gd.get_by_role('tab', name='注册', exact=True).click()
        expect(gd.get_by_role('tab', name='注册')).to_have_attribute('aria-selected', 'true')
        self.dialog_register(guest, username.upper())
        expect(gd.get_by_text('该邮箱已被注册')).to_be_visible()
        gd.get_by_role('button', name='关闭登录窗口').click()
        expect(gd).to_be_hidden()
        self.assertEqual(guest.url, BASE + '/')

    def test_dialog_login_errors_and_backup_pages(self):
        page = self.new_page()
        username = new_username()
        self.api_register(page, username)
        page.request.post(BASE + '/api/auth/logout', data={})
        page.goto(BASE + '/')
        page.locator('nav').get_by_role('button', name='登录', exact=True).click()
        self.dialog_login(page, username, 'wrong password!')
        expect(self.dialog(page).get_by_role('alert')).to_contain_text('密码错误')
        self.dialog_login(page, username.upper())
        expect(self.dialog(page)).to_be_hidden()
        self.assertEqual(page.url, BASE + '/')
        expect(page.get_by_role('button', name=username)).to_be_visible()
        page.request.post(BASE + '/api/auth/logout', data={})
        # backup full pages still work; external redirect targets are rejected
        page.goto(BASE + '/login?redirect=//evil.example/steal')
        page.locator('main').get_by_label('邮箱').fill(username)
        page.locator('main').get_by_label('密码', exact=True).fill(PASSWORD)
        fill_captcha(page.locator('main'))
        page.locator('main').get_by_role('button', name='登录', exact=True).click()
        page.wait_for_url(BASE + '/')
        page.goto(BASE + '/register')
        page.wait_for_url(BASE + '/')  # logged-in users skip the backup pages

    def test_home_ai_tab_resumes_after_login(self):
        page = self.new_page()
        page.route('**/api/parse', lambda r: r.fulfill(json=INFO))
        page.route('**/api/transcript*', lambda r: r.fulfill(status=400, json=dict(detail='无字幕', code='NO_SUBTITLES')))
        username = new_username()
        self.api_register(page, username)
        page.request.post(BASE + '/api/auth/logout', data={})
        page.goto(BASE + '/')
        page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        ai_tab = page.get_by_role('tab', name='AI 视频总结')
        ai_tab.click()
        d = self.dialog(page)
        expect(d.get_by_role('status').filter(has_text='登录后即可使用 AI 视频总结')).to_be_visible()
        expect(ai_tab).to_have_attribute('aria-selected', 'false')
        self.dialog_login(page, username)
        expect(d).to_be_hidden()
        expect(ai_tab).to_have_attribute('aria-selected', 'true')
        expect(page.get_by_role('heading', name='提取结果')).to_be_visible()  # parse resumed in the AI view
        self.assertEqual(page.url, BASE + '/')

    def test_profile_devices_cross_tab_and_expiry(self):
        page = self.new_page()
        username = new_username()
        self.api_register(page, username)
        page.goto(BASE + '/account?section=profile')
        expect(page.get_by_role('heading', level=1)).to_have_text(username)
        page.get_by_label('昵称').fill('  新的昵称  ')
        page.get_by_role('button', name='保存昵称').click()
        expect(page.get_by_role('status').filter(has_text='昵称已更新')).to_be_visible()
        expect(page.get_by_role('button', name='新的昵称')).to_be_visible()
        phone = self.new_page(390, 844)
        phone.goto(BASE + '/')
        phone.get_by_role('button', name='打开导航菜单').click()
        phone.locator('#mobile-navigation').get_by_role('button', name='登录', exact=True).click()
        self.dialog_login(phone, username)
        expect(self.dialog(phone)).to_be_hidden()
        page.reload()
        page.get_by_role('button', name='登录设备', exact=True).click()
        devices = page.locator('#devices-title').locator('xpath=ancestor::section[1]').locator('li')
        expect(devices).to_have_count(2)
        expect(page.get_by_text('当前设备', exact=True)).to_have_count(1)
        page.screenshot(path=SHOTS / 'account-desktop.png', full_page=True)
        page.get_by_role('button', name='下线', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='已下线该设备')).to_be_visible()
        expect(devices).to_have_count(1)
        self.assertIsNone(self.me(phone))
        # revoked device: its next protected request is 401 -> home + "登录已过期" dialog, login returns to /account
        phone.goto(BASE + '/account')
        phone.wait_for_url(BASE + '/')
        expect(self.dialog(phone)).to_be_visible()
        # same browser, two tabs: logging out in one sends the other (on /account) home
        tab2 = self.new_page(context=page.context)
        tab2.goto(BASE + '/account')
        expect(tab2.get_by_role('heading', level=1)).to_have_text('新的昵称')
        page.get_by_role('button', name='新的昵称').click()
        page.get_by_role('menuitem', name='退出登录').click()
        page.wait_for_url(BASE + '/')
        tab2.wait_for_url(BASE + '/')
        expect(page.locator('nav').get_by_role('button', name='登录', exact=True)).to_be_visible()
        # expiry while on a protected page (session revoked from another device)
        self.api_register(page, new_username())
        page.goto(BASE + '/account?section=profile')
        other = self.new_page()
        other.request.post(BASE + '/api/auth/login', data=dict(email=self.me(page)['email'], password=PASSWORD, **captcha_payload(other, BASE)))
        other.request.post(BASE + '/api/account/sessions/revoke-others', data={})
        page.get_by_label('昵称').fill('过期前')
        page.get_by_role('button', name='保存昵称').click()
        page.wait_for_url(BASE + '/')
        d = self.dialog(page)
        expect(d.get_by_role('status').filter(has_text='登录已过期')).to_be_visible()
        self.dialog_login(page, self.me(other)['email'])
        page.wait_for_url(BASE + '/account?section=profile')

    def test_account_sections_validation_and_sync(self):
        page = self.new_page()
        username = new_username()
        self.api_register(page, username)
        page.goto(BASE + '/account?section=profile')
        nav = page.get_by_role('navigation', name='个人中心分区')
        expect(nav.get_by_role('button', name='基本资料')).to_have_attribute('aria-current', 'page')
        expect(page.locator('[aria-labelledby="password-title"]')).to_be_hidden()
        page.get_by_label('昵称').fill('尚未保存')
        page.get_by_role('button', name='取消修改').click()
        expect(page.get_by_label('昵称')).to_have_value(username)
        tab = self.new_page(context=page.context)
        tab.goto(BASE + '/account?section=profile')
        tab.get_by_label('昵称').fill('跨标签昵称')
        tab.get_by_role('button', name='保存昵称').click()
        expect(page.get_by_role('heading', level=1)).to_have_text('跨标签昵称')
        expect(page.get_by_label('昵称')).to_have_value('跨标签昵称')
        page.get_by_label('昵称').fill('本地草稿')
        tab.get_by_label('昵称').fill('另一处的新昵称')
        tab.get_by_role('button', name='保存昵称').click()
        expect(page.get_by_role('heading', level=1)).to_have_text('另一处的新昵称')
        expect(page.get_by_label('昵称')).to_have_value('本地草稿')
        page.get_by_role('button', name='取消修改').click()
        expect(page.get_by_label('昵称')).to_have_value('另一处的新昵称')
        page.get_by_role('button', name='账号安全', exact=True).click()
        page.get_by_role('button', name='修改密码', exact=True).click()
        expect(page.get_by_label('当前密码').first).to_have_attribute('aria-invalid', 'true')
        expect(page.get_by_label('新密码', exact=True)).to_have_attribute('aria-invalid', 'true')
        page.get_by_role('button', name='注销账号', exact=True).click()
        expect(page.get_by_role('button', name='永久注销账号')).to_have_count(0)
        page.get_by_role('button', name='申请注销账号').click()
        page.get_by_label('输入邮箱以确认').fill(username)
        page.get_by_role('button', name='取消注销').click()
        page.get_by_role('button', name='申请注销账号').click()
        expect(page.get_by_label('输入邮箱以确认')).to_have_value('')
        page.screenshot(path=SHOTS / 'account-delete-desktop.png', full_page=True)
        for width in (360, 390, 768, 1440):
            page.set_viewport_size(dict(width=width, height=900))
            for label in ('基本资料', '账号安全', '登录设备', '注销账号'):
                nav.get_by_role('button', name=label, exact=True).click()
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(path=SHOTS / f'account-sections-{width}.png', full_page=True)

    def test_device_refresh_recovers(self):
        page = self.new_page()
        self.api_register(page, new_username())
        page.route('**/api/account/sessions', lambda r: r.fulfill(status=503, json=dict(detail='设备服务暂不可用')))
        page.goto(BASE + '/account')
        page.get_by_role('button', name='登录设备', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('设备服务暂不可用')
        page.unroute('**/api/account/sessions')
        page.get_by_role('button', name='重新加载').click()
        expect(page.get_by_role('alert')).to_have_count(0)
        expect(page.locator('[aria-labelledby="devices-title"] li').first).to_contain_text('当前设备')
        page.get_by_role('button', name='刷新设备').click()
        expect(page.get_by_text('当前设备', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='退出其它所有设备')).to_be_disabled()

    def test_change_password(self):
        page = self.new_page()
        username = new_username()
        self.api_register(page, username)
        page.goto(BASE + '/account')
        page.get_by_role('button', name='账号安全', exact=True).click()
        page.get_by_label('当前密码').first.fill('not my password')
        page.get_by_label('新密码', exact=True).fill('Brand new 2026')
        page.get_by_label('确认新密码').fill('Brand new 2026')
        page.get_by_role('button', name='修改密码', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('当前密码不正确')
        page.get_by_label('当前密码').first.fill(PASSWORD)
        page.get_by_role('button', name='修改密码', exact=True).click()
        page.wait_for_url(BASE + '/')
        d = self.dialog(page)
        expect(d.get_by_role('status').filter(has_text='密码已修改')).to_be_visible()
        self.dialog_login(page, username)
        expect(d.get_by_role('alert')).to_contain_text('密码错误')
        self.dialog_login(page, username, 'Brand new 2026')
        expect(d).to_be_hidden()
        self.assertEqual(page.url, BASE + '/')

    def test_delete_account(self):
        page = self.new_page()
        username = new_username()
        self.api_register(page, username)
        page.goto(BASE + '/account')
        page.get_by_role('button', name='注销账号', exact=True).click()
        page.get_by_role('button', name='申请注销账号').click()
        delete = page.get_by_role('button', name='永久注销账号')
        expect(delete).to_be_disabled()
        page.get_by_label('当前密码').nth(1).fill(PASSWORD)
        page.get_by_label('输入邮箱以确认').fill(username)
        delete.click()
        page.wait_for_url(BASE + '/')
        expect(page.get_by_role('status').filter(has_text='账号已注销')).to_be_visible()
        expect(self.dialog(page)).to_be_hidden()
        page.locator('nav').get_by_role('button', name='登录', exact=True).click()
        self.dialog_login(page, username)
        expect(self.dialog(page).get_by_role('alert')).to_contain_text('该邮箱尚未注册')

    def test_mobile_dialog_and_navigation(self):
        page = self.new_page(390, 844)
        page.goto(BASE + '/')
        page.get_by_role('button', name='打开导航菜单').click()
        menu = page.locator('#mobile-navigation')
        menu.get_by_role('button', name='免费注册').click()
        d = self.dialog(page)
        expect(d.get_by_role('tab', name='注册')).to_have_attribute('aria-selected', 'true')
        box = d.bounding_box()
        self.assertLessEqual(box['x'] + box['width'], 390)
        self.assertGreaterEqual(box['x'], 0)
        page.screenshot(path=SHOTS / 'dialog-register-mobile.png')
        email = new_username()
        self.dialog_register(page, email)
        expect(d).to_be_hidden()
        page.get_by_role('button', name='打开导航菜单').click()
        expect(menu.get_by_text(email.split('@')[0], exact=True)).to_be_visible()
        page.wait_for_timeout(300)  # 200ms enter transition
        page.screenshot(path=SHOTS / 'mobile-menu-user.png')
        menu.get_by_role('link', name='个人中心').click()
        page.wait_for_url(BASE + '/account')
        expect(page.get_by_role('heading', level=1)).to_have_text(email.split('@')[0])
        expect(page.get_by_role('button', name='关闭升级提示')).to_have_count(0)
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        page.screenshot(path=SHOTS / 'account-mobile.png', full_page=True)
        page.get_by_role('button', name='打开导航菜单').click()
        menu.get_by_role('button', name='退出登录').click()
        page.wait_for_url(BASE + '/')
        self.assertIsNone(self.me(page))


if __name__ == '__main__':
    unittest.main(verbosity=2)
