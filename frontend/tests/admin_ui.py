"""Mocked backend administration UI. Vite must run on :5178; never touches a database.

Run: python -P frontend/tests/admin_ui.py
Screenshots: .runtime/admin-ui/. All /api responses are mocked.
"""
import json
import os
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect, sync_playwright

BASE = os.getenv('FREEVIDEO_UI_BASE', 'http://127.0.0.1:5178')
SHOTS = Path(__file__).resolve().parents[2] / '.runtime' / 'admin-ui'
SUPER = dict(id=1, username='chief_admin', nickname='主管理员', role='superadmin', status='active', created_at='2026-11-16T02:00:00Z')
OPERATOR = dict(SUPER, id=2, username='staff_admin', nickname='运营管理员', role='admin')
SITE = dict(id=100, username='site_user', nickname='网站用户', email='site@example.com')


class AdminUI(unittest.TestCase):
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
        self.admin = dict(SUPER)
        self.fail_admin_me = False
        self.staff = [dict(SUPER), dict(OPERATOR)]
        self.users = [dict(id=i, email=f'member{i:02}@example.com', nickname=f'学习用户 {i}',
                           email_verified=i % 2 == 1, status='disabled' if i == 2 else 'active',
                           created_at='2026-11-15T04:10:00Z', disabled_at=None, disabled_reason=None,
                           membership=dict(plan='free', name='免费版', expires_at=None)) for i in range(1, 22)]
        self.posts = []
        self.errors = []
        self.page = self.browser.new_page(viewport=dict(width=1440, height=1000))
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.route('**/api/**', self.api)

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def api(self, route):
        req = route.request
        url = urlparse(req.url)
        path, method = url.path, req.method
        query = parse_qs(url.query)
        body = req.post_data_json if req.post_data else {}
        if path == '/api/auth/me': return route.fulfill(json=dict(user=SITE))
        if path == '/api/health': return route.fulfill(json=dict(ok=True, ai_enabled=False, asr_enabled=False))
        if path == '/api/admin/auth/me':
            if self.fail_admin_me: return route.fulfill(status=503, json=dict(detail='后台账号服务暂不可用', code='ADMIN_SERVICE_UNAVAILABLE'))
            return route.fulfill(json=dict(admin=self.admin))
        if path == '/api/admin/auth/login':
            self.posts.append((path, body))
            self.admin = dict(SUPER)
            return route.fulfill(json=dict(admin=self.admin))
        if path == '/api/admin/auth/logout':
            self.admin = None
            return route.fulfill(json=dict(ok=True))
        if path == '/api/admin/auth/password':
            self.posts.append((path, body))
            self.admin = None
            return route.fulfill(json=dict(ok=True))
        if not self.admin and path.startswith('/api/admin/'):
            return route.fulfill(status=401, json=dict(detail='后台登录已过期', code='ADMIN_AUTH_REQUIRED'))
        if path in ('/api/admin/users', '/api/admin/staff') and method == 'GET':
            source = self.users if path.endswith('/users') else self.staff
            search, status, verified = query.get('search', [''])[0], query.get('status', ['all'])[0], query.get('verified', ['all'])[0]
            source = [u for u in source if (not search or search.lower() in json.dumps(u, ensure_ascii=False).lower())
                      and (status == 'all' or u['status'] == status)
                      and (verified == 'all' or bool(u.get('email_verified')) == (verified == 'verified'))]
            page = int(query.get('page', [1])[0])
            return route.fulfill(json=dict(items=source[(page-1)*20:page*20], total=len(source), page=page, page_size=20))
        if path.startswith('/api/admin/users/'):
            user = next(u for u in self.users if u['id'] == int(path.split('/')[4]))
            if method == 'PATCH':
                self.posts.append((path, body)); user.update(status=body['status'], disabled_reason=body.get('reason'), disabled_at='2026-11-16T03:00:00Z' if body['status'] == 'disabled' else None)
                return route.fulfill(json=dict(user=user))
            return route.fulfill(json=user)
        if path == '/api/admin/staff' and method == 'POST':
            self.posts.append((path, body))
            staff = dict(SUPER, id=len(self.staff)+1, username=body['username'], nickname=body['nickname'], role=body['role'])
            self.staff.append(staff)
            return route.fulfill(json=dict(admin=staff))
        if path.startswith('/api/admin/staff/'):
            staff = next(u for u in self.staff if u['id'] == int(path.split('/')[4]))
            self.posts.append((path, body))
            if path.endswith('/password'): return route.fulfill(json=dict(ok=True, admin=staff))
            if staff['id'] == 1 and body.get('role') == 'admin':
                return route.fulfill(status=409, json=dict(detail='至少保留一个启用的超级管理员', code='ADMIN_LAST_SUPERADMIN'))
            staff.update(body)
            return route.fulfill(json=dict(admin=staff))
        route.fulfill(json=dict(ok=True, plans=[]))

    def test_login_guard_and_front_session_isolation(self):
        self.admin = None
        self.page.goto(BASE + '/admin/users')
        expect(self.page.get_by_role('heading', name='后台登录', exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_role('dialog').count(), 0)
        self.page.get_by_label('后台登录名', exact=True).fill('chief_admin')
        self.page.get_by_label('密码', exact=True).fill('Admin test password')
        self.page.get_by_role('button', name='登录后台', exact=True).click()
        expect(self.page.get_by_role('heading', name='注册用户', exact=True)).to_be_visible()
        self.page.evaluate("async () => { const {account}=await import('/src/account.js'); await account.refresh(); account.markLoggedOut('expired'); }")
        expect(self.page.get_by_role('heading', name='注册用户', exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_role('dialog').count(), 0)
        self.page.evaluate("async () => { const {account}=await import('/src/account.js'); await account.refresh(); }")
        self.page.get_by_role('button', name='退出', exact=True).click()
        expect(self.page.get_by_role('heading', name='后台登录', exact=True)).to_be_visible()
        self.assertEqual(self.page.evaluate("async()=> (await import('/src/account.js')).account.user.id"), SITE['id'])

    def test_users_search_paging_details_and_status(self):
        self.page.goto(BASE + '/admin/users')
        self.page.get_by_role('button', name='下一页', exact=True).click()
        expect(self.page.get_by_text('member21@example.com', exact=True).first).to_be_visible()
        self.page.get_by_placeholder('邮箱、昵称或用户 ID').fill('member01@')
        self.page.get_by_role('button', name='搜索', exact=True).click()
        expect(self.page.get_by_text('共 1 条 · 第 1 / 1 页')).to_be_visible()
        self.page.get_by_role('button', name='查看 member01@example.com 详情').click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_contain_text('注册用户详情')
        expect(dialog).to_contain_text('免费版')
        dialog.get_by_role('button', name='关闭对话框').click()
        self.page.get_by_role('button', name='禁用 member01@example.com').click()
        dialog = self.page.get_by_role('dialog')
        dialog.get_by_label('禁用原因（选填）').fill('测试禁用原因')
        dialog.get_by_role('button', name='确认禁用', exact=True).click()
        expect(self.page.get_by_role('button', name='启用 member01@example.com')).to_be_visible()
        self.assertEqual(self.users[0]['disabled_reason'], '测试禁用原因')
        self.page.get_by_role('button', name='启用 member01@example.com').click()
        self.page.get_by_role('dialog').get_by_role('button', name='确认启用', exact=True).click()
        expect(self.page.get_by_role('button', name='禁用 member01@example.com')).to_be_visible()
        self.page.get_by_placeholder('邮箱、昵称或用户 ID').fill('')
        self.page.get_by_label('账号状态', exact=True).select_option('disabled')
        expect(self.page.get_by_text('member02@example.com', exact=True).first).to_be_visible()
        self.assertIn('status=disabled', self.page.url)

    def test_staff_create_edit_reset_and_last_superadmin(self):
        self.page.goto(BASE + '/admin/staff')
        self.page.get_by_role('button', name='新增后台账号', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        for label, value in [('后台登录名', 'new_admin'), ('显示名称', '新运营人员'), ('初始密码', 'new admin password')]: dialog.get_by_label(label, exact=True).fill(value)
        dialog.get_by_role('button', name='创建后台账号', exact=True).click()
        expect(self.page.get_by_role('button', name='编辑 new_admin', exact=True)).to_be_visible()
        self.page.get_by_role('button', name='编辑 new_admin', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        dialog.get_by_label('显示名称', exact=True).fill('已更新人员')
        dialog.get_by_label('账号状态', exact=True).select_option('disabled')
        dialog.get_by_role('button', name='保存修改', exact=True).click()
        expect(self.page.get_by_text('已更新人员', exact=True).first).to_be_visible()
        self.page.get_by_role('button', name='重置 new_admin 密码', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        dialog.get_by_label('新密码', exact=True).fill('reset admin password')
        dialog.get_by_role('button', name='确认重置密码', exact=True).click()
        expect(self.page.get_by_text('已重置 new_admin 的密码', exact=False)).to_be_visible()
        self.page.get_by_role('button', name='编辑 chief_admin', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog.get_by_label('账号状态', exact=True)).to_be_disabled()
        dialog.get_by_label('角色', exact=True).select_option('admin')
        dialog.get_by_role('button', name='保存修改', exact=True).click()
        expect(dialog.get_by_role('alert')).to_contain_text('至少保留一个启用的超级管理员')

    def test_permissions_expiry_and_own_password(self):
        self.admin = dict(OPERATOR)
        self.page.goto(BASE + '/admin/staff')
        expect(self.page.get_by_role('heading', name='注册用户', exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_role('link', name='后台账号', exact=True).count(), 0)
        self.page.get_by_role('button', name='修改密码', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        dialog.get_by_label('当前密码', exact=True).fill('old password')
        dialog.get_by_label('新密码', exact=True).fill('new operator password')
        dialog.get_by_role('button', name='修改密码并退出', exact=True).click()
        expect(self.page.get_by_role('heading', name='后台登录', exact=True)).to_be_visible()
        expect(self.page.get_by_role('status')).to_contain_text('后台密码已修改')

    def test_role_refresh_and_backend_404(self):
        self.page.goto(BASE + '/admin/staff')
        expect(self.page.get_by_role('heading', name='后台账号', exact=True)).to_be_visible()
        self.admin = dict(SUPER, role='admin')
        self.page.evaluate("() => {const channel=new BroadcastChannel('fv-admin-auth');channel.postMessage({type:'admin-changed',sessionChanged:false});setTimeout(()=>channel.close(),100)}")
        expect(self.page.get_by_role('heading', name='注册用户', exact=True)).to_be_visible()
        self.page.goto(BASE + '/admin/missing-page')
        expect(self.page.get_by_role('heading', name='后台页面不存在', exact=True)).to_be_visible()

    def test_cross_tab_identity_failure_can_retry_current_page(self):
        self.page.goto(BASE + '/admin/users?search=member01')
        expect(self.page.get_by_role('heading', name='注册用户', exact=True)).to_be_visible()
        self.page.evaluate("async () => { const {account}=await import('/src/account.js'); await account.refresh(); }")
        self.fail_admin_me = True
        self.page.evaluate("() => {const channel=new BroadcastChannel('fv-admin-auth');channel.postMessage({type:'admin-changed',sessionChanged:true});setTimeout(()=>channel.close(),100)}")
        expect(self.page.get_by_role('heading', name='后台连接暂不可用', exact=True)).to_be_visible()
        expect(self.page.get_by_role('alert')).to_contain_text('后台账号服务暂不可用')
        self.assertIn('/admin/users?search=member01', self.page.url)
        self.assertEqual(self.page.get_by_role('dialog').count(), 0)
        self.assertEqual(self.page.evaluate("async()=> (await import('/src/account.js')).account.user.id"), SITE['id'])
        self.fail_admin_me = False
        self.page.get_by_role('button', name='重试连接', exact=True).click()
        expect(self.page.get_by_role('heading', name='注册用户', exact=True)).to_be_visible()
        expect(self.page.get_by_placeholder('邮箱、昵称或用户 ID')).to_have_value('member01')
        expect(self.page.get_by_text('共 1 条 · 第 1 / 1 页')).to_be_visible()

    def test_responsive_screenshots(self):
        for width in (1440, 390):
            self.page.set_viewport_size(dict(width=width, height=900))
            for path, heading in [('users', '注册用户'), ('staff', '后台账号')]:
                self.page.goto(BASE + '/admin/' + path)
                expect(self.page.get_by_role('heading', name=heading, exact=True)).to_be_visible()
                expect(self.page.get_by_role('button', name='下一页', exact=True)).to_be_visible()
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                for select in self.page.get_by_role('combobox').all():
                    self.assertGreaterEqual(select.bounding_box()['width'], 100)
                    self.assertLessEqual(select.evaluate('el => el.parentElement.querySelector("span").getBoundingClientRect().height'), 24)
                self.page.screenshot(path=str(SHOTS / f'{path}-{width}.png'), full_page=True)
                self.page.screenshot(path=str(SHOTS / f'{path}-{width}-viewport.png'))


if __name__ == '__main__': unittest.main(verbosity=2)
