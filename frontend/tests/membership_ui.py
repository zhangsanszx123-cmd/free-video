"""Membership/history browser checks against :8010 and a dedicated MySQL test DB.

Run after npm run build and starting the test backend as in account_ui.py.
Seeds only freevideo_test through the existing repository. No media downloads, ASR or payments.
"""
import os
from pathlib import Path
import secrets
import subprocess
import unittest

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
BASE = os.getenv('ACCOUNT_UI_BASE', 'http://127.0.0.1:8010')
SHOTS = ROOT / '.runtime' / 'membership-ui'
PASSWORD = 'Quota UI 2026'


class MembershipUI(unittest.TestCase):
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
        self.context = self.browser.new_context(viewport=dict(width=1440, height=1000))
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.username = 'quota_ui_' + secrets.token_hex(4)
        response = self.page.request.post(BASE + '/api/auth/register', data=dict(username=self.username, password=PASSWORD))
        self.assertTrue(response.ok, response.text())

    def tearDown(self):
        self.page.request.delete(BASE + '/api/account', data=dict(password=PASSWORD, confirm_username=self.username))
        self.context.close()
        self.assertEqual(self.errors, [])

    def seed(self, plan=None):
        code = '''
import sys, uuid
from app import account_store, config, membership
from app.transcriptions import Transcription
assert config.MYSQL_DATABASE == 'freevideo_test'
with account_store._cursor() as cur:
    cur.execute('SELECT id FROM users WHERE username_key=%s', (sys.argv[1],))
    uid = cur.fetchone()['id']
if len(sys.argv) > 2:
    membership.grant(sys.argv[1], sys.argv[2])
for i, source in enumerate(['asr','platform_subtitle']):
    job = Transcription(uuid.uuid4().hex, f'user:{uid}', str(i)*64, f'https://example.com/video/{i}', None, True,
                        title='识别额度测试视频' if i == 0 else '免费平台字幕视频')
    membership.create_record(job)
    membership.persist(job, {'duration':91,'platform':'测试平台'})
    if source == 'asr': membership.reserve(uid, job.id, 91, job.key)
    payload = {**job.public(), 'status':'done', 'stage':'done', 'result':{'source':source,'text':'这是一段历史文稿 <script>不执行脚本</script>', 'srt':'1\\n00:00:00,000 --> 00:00:01,000\\n历史文稿', 'timed_text':'[00:00] 历史文稿'}}
    membership.complete(job, payload, 'settled' if source == 'asr' else 'released')
'''
        env = {**os.environ, 'MYSQL_DATABASE': 'freevideo_test', 'PYTHONIOENCODING': 'utf-8'}
        result = subprocess.run([str(ROOT / 'backend/.venv/Scripts/python.exe'), '-c', code, self.username] + ([plan] if plan else []),
                                cwd=ROOT / 'backend', env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_quota_menu_and_server_plans(self):
        p = self.page
        p.goto(BASE + '/account')
        p.get_by_role('button', name='会员与额度', exact=True).click()
        quota = p.get_by_role('region', name='语音识别额度')
        expect(quota).to_contain_text('剩余 30分钟')
        summary = p.request.get(BASE + '/api/account/membership').json()
        registered = p.request.get(BASE + '/api/auth/me').json()['user']['created_at']
        from datetime import datetime
        # Public account timestamps are rounded to seconds; quota anchors retain DB microseconds.
        self.assertEqual(datetime.fromisoformat(summary['period_start']).replace(microsecond=0),
                         datetime.fromisoformat(registered.replace('Z', '+00:00')))
        self.assertEqual(summary['reset_basis'], 'registration')
        expect(quota).to_contain_text('下次重置')
        p.locator('nav').get_by_role('button', name=self.username, exact=True).click()
        menu = p.get_by_role('menu')
        expect(menu).to_contain_text('每月 30分钟')
        expect(menu).to_contain_text('下次重置')
        expect(menu.get_by_role('menuitem', name='历史任务')).to_be_visible()
        profile = menu.get_by_role('menuitem', name=f'{self.username}，个人中心', exact=True)
        expect(profile.get_by_text('普通用户', exact=True)).to_be_visible()
        menu.screenshot(path=SHOTS / 'account-menu.png')
        profile.focus()
        p.keyboard.press('Enter')
        expect(menu).to_be_hidden()  # Also closes when already on /account.
        expect(p).to_have_url(BASE + '/account')
        p.goto(BASE + '/pricing')
        cards = p.locator('article')
        expect(cards).to_have_count(3)
        expect(cards.nth(1)).to_contain_text('19.9')
        expect(cards.nth(1)).to_contain_text('10小时')
        expect(cards.nth(1)).to_contain_text('Pro 额度不叠加免费额度')
        expect(cards.nth(0)).to_contain_text('按注册时间逐月重置')
        expect(cards.nth(1)).to_contain_text('按 Pro 开通时间逐月重置')
        expect(p.get_by_text('每月 1 日重置', exact=False)).to_have_count(0)
        expect(cards.nth(2)).to_contain_text('99')
        expect(cards.nth(2)).to_contain_text('30小时')
        # Backend runs without ZPAY credentials here; payment flows live in payment_ui.py.
        expect(cards.nth(1)).to_contain_text('在线支付暂未开放')
        p.get_by_role('button', name='开通月卡', exact=True).click()
        expect(p.get_by_role('dialog')).to_contain_text('会员在线支付功能即将上线')
        p.keyboard.press('Escape')
        p.screenshot(path=SHOTS / 'pricing-desktop.png', full_page=True)

    def test_real_history_export_search_delete(self):
        self.seed()
        p = self.page
        p.goto(BASE + '/history')
        expect(p.locator('article')).to_have_count(2)
        article = p.locator('article').filter(has=p.get_by_role('heading', name='识别额度测试视频'))
        expect(article).to_contain_text('已扣 1分钟31秒')
        article.get_by_role('button', name='查看文稿').click()
        self.assertIn('<script>', article.get_by_role('textbox').input_value())
        with p.expect_download() as event:
            article.get_by_role('link', name='导出 SRT').click()
        self.assertTrue(event.value.suggested_filename.endswith('.srt'))
        p.get_by_role('textbox', name='搜索任务').fill('识别额度')
        p.get_by_role('button', name='搜索', exact=True).click()
        expect(p.locator('article')).to_have_count(1)
        p.screenshot(path=SHOTS / 'history-desktop.png', full_page=True)
        article.get_by_role('button', name='移出历史').click()
        expect(p.get_by_role('heading', name='暂无匹配的任务')).to_be_visible()
        self.assertEqual(p.request.get(BASE + '/api/account/membership').json()['used_seconds'], 91)
        p.get_by_role('combobox', name='任务状态').select_option('active')
        expect(p.get_by_role('heading', name='暂无执行中的任务')).to_be_visible()

    def test_membership_and_history_errors_retry(self):
        p = self.page
        p.route('**/api/account/membership', lambda r: r.fulfill(status=503, json=dict(detail='额度服务暂不可用')))
        p.goto(BASE + '/account')
        p.get_by_role('button', name='会员与额度', exact=True).click()
        expect(p.get_by_role('alert')).to_contain_text('额度服务暂不可用')
        p.unroute('**/api/account/membership')
        p.get_by_role('button', name='刷新额度').click()
        expect(p.get_by_role('region', name='语音识别额度')).to_contain_text('剩余 30分钟')
        p.route('**/api/account/history?*', lambda r: r.fulfill(status=503, json=dict(detail='任务服务暂不可用')))
        p.goto(BASE + '/history')
        expect(p.get_by_role('alert')).to_contain_text('任务服务暂不可用')
        p.unroute('**/api/account/history?*')
        p.get_by_role('button', name='刷新', exact=True).click()
        expect(p.get_by_role('heading', name='暂无匹配的任务')).to_be_visible()

    def test_guest_asr_prompts_login_and_resumes(self):
        p = self.page
        p.request.post(BASE + '/api/auth/logout', data={})
        info = dict(url='https://example.com/guest-asr', title='登录识别测试', platform='Test',
                    qualities=[dict(height=720, label='720P')], subtitles=[], duration=60)
        p.route('**/api/parse', lambda r: r.fulfill(json=info))
        p.route('**/api/transcript', lambda r: r.fulfill(status=400, json=dict(detail='没有字幕', code='NO_SUBTITLES')))
        p.route('**/api/health', lambda r: r.fulfill(json=dict(ok=True, ai_enabled=False, asr_enabled=True, asr_ready=True, max_batch=20)))
        submissions = []
        def reject(r):
            submissions.append(r.request.post_data)
            r.fulfill(status=403, json=dict(detail='测试额度不足', code='QUOTA_EXCEEDED', retryable=False))
        p.route('**/api/transcriptions', reject)
        p.goto(BASE + '/')
        p.get_by_role('textbox', name='视频链接或分享口令').fill(info['url'])
        p.get_by_role('button', name='立即解析', exact=True).click()
        dialog = p.locator('dialog[aria-labelledby="auth-title"]')
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('登录后可使用每月免费语音识别额度')
        self.assertEqual(submissions, [])
        dialog.get_by_label('用户名').fill(self.username)
        dialog.get_by_label('密码', exact=True).fill(PASSWORD)
        dialog.get_by_role('button', name='登录', exact=True).click()
        expect(dialog).to_be_hidden()
        expect(p.get_by_text('测试额度不足', exact=True)).to_be_visible()
        self.assertEqual(len(submissions), 1)

    def test_paid_snapshot_and_responsive_layouts(self):
        self.seed('yearly')
        p = self.page
        for width in (360, 390, 768, 1440):
            p.set_viewport_size(dict(width=width, height=1000))
            p.goto(BASE + '/account')
            p.get_by_role('button', name='会员与额度', exact=True).click()
            expect(p.get_by_role('region', name='语音识别额度')).to_contain_text('年卡会员')
            expect(p.get_by_role('region', name='语音识别额度')).to_contain_text('每月 30小时')
            expect(p.get_by_role('region', name='语音识别额度')).to_contain_text('下次重置')
            self.assertTrue(p.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            p.screenshot(path=SHOTS / f'quota-{width}.png', full_page=True)
            if width < 768:
                p.get_by_role('button', name='打开导航菜单').click()
                menu = p.locator('#mobile-navigation')
                profile = menu.get_by_role('link', name=f'{self.username}，个人中心', exact=True)
            else:
                p.locator('nav').get_by_role('button', name=self.username, exact=True).click()
                menu = p.get_by_role('menu')
                profile = menu.get_by_role('menuitem', name=f'{self.username}，个人中心', exact=True)
            expect(profile.get_by_text('PRO 用户', exact=True)).to_be_visible()
            menu.screenshot(path=SHOTS / f'pro-menu-{width}.png')
            profile.click()
            expect(menu).to_be_hidden()
            for path in ('/history', '/pricing'):
                p.goto(BASE + path)
                if path == '/history': expect(p.locator('article')).to_have_count(2)
                else: expect(p.locator('article')).to_have_count(3)
                self.assertTrue(p.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                p.screenshot(path=SHOTS / f'{path[1:]}-{width}.png', full_page=True)


    def test_last_monthly_cycle_is_labelled_as_membership_expiry(self):
        self.seed('monthly')
        p = self.page
        p.goto(BASE + '/account?section=membership')
        quota = p.get_by_role('region', name='语音识别额度')
        expect(quota).to_contain_text('每月 10小时')
        expect(quota).to_contain_text('会员到期')
        summary = p.request.get(BASE + '/api/account/membership').json()
        self.assertEqual(summary['limit_seconds'], 36000)
        self.assertEqual(summary['available_seconds'], 36000 - 91)
        self.assertEqual(summary['resets_at'], summary['expires_at'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
