"""Real admin browser integration against admin_test_server.py on :8015.

Uses only freevideo_admin_ui_test fixture accounts. No email or payment is sent.
Run after building frontend and starting the isolated test server.
"""
from pathlib import Path
import secrets
import unittest

from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:8015'
PASSWORD = 'Admin UI password 2026'
SHOTS = Path(__file__).resolve().parents[2] / '.runtime/admin-live-ui'


class AdminRealUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        SHOTS.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport=dict(width=1440, height=1000))
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def login(self, page, username='admin_fixture', password=PASSWORD):
        page.goto(BASE + '/admin/users')
        expect(page.get_by_role('heading', name='后台登录', exact=True)).to_be_visible()
        page.get_by_label('后台登录名', exact=True).fill(username)
        page.get_by_label('密码', exact=True).fill(password)
        page.get_by_role('button', name='登录后台', exact=True).click()
        page.wait_for_url(BASE + '/admin/users')
        expect(page.get_by_role('heading', name='注册用户', exact=True)).to_be_visible()

    def search(self, label, value):
        self.page.get_by_label(label, exact=True).fill(value)
        self.page.get_by_role('button', name='搜索', exact=True).click()

    def test_registered_user_enable_disable_and_login_isolation(self):
        self.login(self.page)
        email = 'admin-member-00@example.com'
        result = self.page.request.post(BASE + '/api/auth/login', data=dict(email=email, password='Site UI password 2026'))
        self.assertEqual(result.status, 200)
        self.search('搜索注册用户', email)
        detail = self.page.request.get(BASE + '/api/admin/users?search=' + email).json()['items'][0]
        uid = detail['id']
        before = self.page.request.get(BASE + f'/api/admin/users/{uid}').json()
        self.page.get_by_role('button', name=f'查看 {email} 详情', exact=True).click()
        dialog = self.page.locator('dialog[open]')
        expect(dialog).to_contain_text('月卡会员')
        dialog.get_by_role('button', name='关闭对话框').click()
        self.page.get_by_role('button', name=f'禁用 {email}', exact=True).click()
        dialog = self.page.locator('dialog[open]')
        dialog.get_by_label('禁用原因（选填）').fill('真实后端浏览器测试')
        dialog.get_by_role('button', name='确认禁用', exact=True).click()
        expect(self.page.get_by_role('button', name=f'启用 {email}', exact=True)).to_be_visible()
        self.assertIsNone(self.page.request.get(BASE + '/api/auth/me').json()['user'])
        self.assertEqual(self.page.request.get(BASE + '/api/admin/auth/me').json()['admin']['username'], 'admin_fixture')
        denied = self.page.request.post(BASE + '/api/auth/login', data=dict(email=email, password='Site UI password 2026'))
        self.assertEqual(denied.status, 403)
        self.page.get_by_role('button', name=f'启用 {email}', exact=True).click()
        self.page.locator('dialog[open]').get_by_role('button', name='确认启用', exact=True).click()
        expect(self.page.get_by_role('button', name=f'禁用 {email}', exact=True)).to_be_visible()
        after = self.page.request.get(BASE + f'/api/admin/users/{uid}').json()
        self.assertEqual(after['membership'], before['membership'])
        self.assertEqual(after['created_at'], before['created_at'])
        self.assertEqual(self.page.request.post(BASE + '/api/auth/login', data=dict(email=email, password='Site UI password 2026')).status, 200)
        self.page.get_by_role('button', name='退出', exact=True).click()
        expect(self.page.get_by_role('heading', name='后台登录', exact=True)).to_be_visible()
        self.assertTrue(self.page.url.startswith(BASE + '/admin/login?redirect='))
        self.assertIsNotNone(self.page.request.get(BASE + '/api/auth/me').json()['user'])

    def test_staff_create_edit_reset_password_and_session_revocation(self):
        self.login(self.page)
        self.page.get_by_role('link', name='后台账号', exact=True).click()
        username = 'ui_staff_' + secrets.token_hex(3)
        initial = 'Staff UI temporary 2026'
        updated = 'Staff UI changed 2026'
        self.page.get_by_role('button', name='新增后台账号', exact=True).click()
        dialog = self.page.locator('dialog[open]')
        dialog.get_by_label('后台登录名', exact=True).fill(username)
        dialog.get_by_label('显示名称', exact=True).fill('浏览器新增管理员')
        dialog.get_by_label('初始密码', exact=True).fill(initial)
        dialog.get_by_role('button', name='创建后台账号', exact=True).click()
        expect(self.page.get_by_role('button', name=f'编辑 {username}', exact=True)).to_be_visible()
        context = self.browser.new_context()
        operator = context.new_page()
        operator.on('pageerror', lambda error: self.errors.append(str(error)))
        try:
            self.login(operator, username, initial)
            expect(operator.get_by_role('link', name='后台账号', exact=True)).to_have_count(0)
            self.assertEqual(operator.request.get(BASE + '/api/admin/staff').status, 403)
            self.page.get_by_role('button', name=f'编辑 {username}', exact=True).click()
            dialog = self.page.locator('dialog[open]')
            dialog.get_by_label('显示名称', exact=True).fill('浏览器更新名称')
            dialog.get_by_label('账号状态').select_option('disabled')
            dialog.get_by_role('button', name='保存修改', exact=True).click()
            expect(self.page.locator('dialog[open]')).to_have_count(0)
            operator.reload()
            expect(operator.get_by_role('heading', name='后台登录', exact=True)).to_be_visible()
            self.page.get_by_role('button', name=f'编辑 {username}', exact=True).click()
            dialog = self.page.locator('dialog[open]')
            dialog.get_by_label('账号状态').select_option('active')
            dialog.get_by_role('button', name='保存修改', exact=True).click()
            expect(self.page.locator('dialog[open]')).to_have_count(0)
            self.page.get_by_role('button', name=f'重置 {username} 密码', exact=True).click()
            dialog = self.page.locator('dialog[open]')
            dialog.get_by_label('新密码', exact=True).fill(updated)
            dialog.get_by_role('button', name='确认重置密码', exact=True).click()
            expect(self.page.locator('dialog[open]')).to_have_count(0)
            old = operator.request.post(BASE + '/api/admin/auth/login', data=dict(username=username, password=initial))
            self.assertEqual(old.status, 401)
            self.login(operator, username, updated)
            self.assertEqual(operator.request.get(BASE + '/api/admin/auth/me').json()['admin']['nickname'], '浏览器更新名称')
        finally:
            context.close()

    def test_mobile_users_staff_and_dialog_layout(self):
        self.page.set_viewport_size(dict(width=390, height=844))
        self.login(self.page)
        self.search('搜索注册用户', 'admin-member-01@example.com')
        expect(self.page.get_by_role('button', name='查看 admin-member-01@example.com 详情', exact=True)).to_be_visible()
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.page.screenshot(path=str(SHOTS / 'users-390.png'), full_page=True)
        self.page.get_by_role('button', name='查看 admin-member-01@example.com 详情', exact=True).click()
        expect(self.page.locator('dialog[open]')).to_contain_text('admin-member-01@example.com')
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.page.locator('dialog[open]').get_by_role('button', name='关闭对话框').click()
        self.page.get_by_role('link', name='后台账号', exact=True).click()
        expect(self.page.get_by_role('button', name='新增后台账号', exact=True)).to_be_visible()
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.page.screenshot(path=str(SHOTS / 'staff-390.png'), full_page=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
