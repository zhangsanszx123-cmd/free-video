"""Guest AI trial browser checks. All APIs mocked; Vite :5178 or UI_BASE_URL.

No real platform, cloud recognition, AI, account database or payment is called.
"""
import copy
import os
from pathlib import Path
import re
import unittest

from playwright.sync_api import expect, sync_playwright

BASE = os.getenv('UI_BASE_URL', 'http://127.0.0.1:5178')
VIDEO = 'https://example.com/guest-video'
USER = dict(id=1, email='tester@example.com', username='tester', nickname='Tester', created_at='2026-11-28T00:00:00Z')
INFO = dict(url=VIDEO, title='游客体验视频', duration=120, platform='Test', qualities=[], subtitles=[])
TASK = dict(id='guest-task-1', url=VIDEO, status='done', stage='done', message='总结完成', error=None,
            error_code=None, retryable=False, info=INFO, summary='## 游客总结结果\n\n这是免费体验的核心要点。',
            transcript=dict(text='这是文稿', timed_text='[00:01] 这是文稿', source='asr'), created_at=1, finished_at=2)


class GuestAiTrialUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.user = None
        self.available = True
        self.latest = None
        self.next_post = copy.deepcopy(TASK)
        self.next_poll = copy.deepcopy(TASK)
        self.post_error = None
        self.trial_posts = []
        self.polls = []
        self.protected = []
        self.post_handler = None
        self.status_handler = None
        self.page.route(re.compile('^' + re.escape(BASE) + '/api/'), self.route)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def route(self, route):
        path = route.request.url.split('/api/', 1)[-1]
        method = route.request.method
        if path == 'auth/me':
            return route.fulfill(json=dict(user=self.user))
        if path == 'auth/login':
            self.user = USER
            return route.fulfill(json=dict(user=self.user))
        if path == 'health':
            return route.fulfill(json=dict(ok=True, ai_enabled=True, asr_enabled=True, asr_max_minutes=60, max_batch=20))
        if path == 'guest/ai-summary':
            if method == 'GET':
                if self.status_handler:
                    return self.status_handler(route)
                return route.fulfill(json=dict(available=self.available, max_seconds=180, task=self.latest))
            self.trial_posts.append(route.request.post_data_json)
            if self.post_handler:
                return self.post_handler(route)
            if self.post_error:
                return route.fulfill(status=403, json=self.post_error)
            self.latest = copy.deepcopy(self.next_post)
            return route.fulfill(json=self.latest)
        if path.startswith('guest/ai-summary/'):
            self.polls.append(path)
            self.latest = copy.deepcopy(self.next_poll)
            return route.fulfill(json=self.latest)
        if path == 'parse':
            self.protected.append(path)
            return route.fulfill(json=dict(INFO, url=route.request.post_data_json['url']))
        if path == 'learn/summary':
            self.protected.append(path)
            return route.fulfill(body='event: delta\ndata: "登录后的总结"\n\nevent: done\ndata: true\n\n', content_type='text/event-stream')
        if path.startswith(('transcri', 'learn/')):
            self.protected.append(path)
            return route.fulfill(json=dict(text='文稿', timed_text='[00:01] 文稿'))
        if path == 'account/membership':
            return route.fulfill(json=dict(plan='free', name='免费用户', limit_seconds=1800, available_seconds=1800,
                used_seconds=0, reserved_seconds=0, asr_max_minutes=8, ai_limit=10, ai_used=0, chat_daily_limit=1, chat_used_today=0))
        return route.fulfill(json=dict(ok=True, plans=[]))

    def start(self, url=VIDEO):
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(url)
        self.page.get_by_role('tab', name='AI 视频总结', exact=True).click()
        expect(self.page.locator('dialog[open]')).to_have_count(0)
        self.page.get_by_role('button', name='AI 总结', exact=True).click()

    def login(self):
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        dialog.get_by_label('邮箱', exact=True).fill('tester@example.com')
        dialog.get_by_label('密码', exact=True).fill('password123')
        dialog.get_by_role('button', name='登录', exact=True).click()
        expect(dialog).not_to_be_visible()

    def test_trial_includes_no_subtitle_result_without_using_normal_parse(self):
        for width in (1440, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width, height=960))
                self.latest = None
                self.trial_posts.clear()
                self.protected.clear()
                self.start()
                expect(self.page.get_by_role('heading', name='游客总结结果')).to_be_visible()
                expect(self.page.get_by_text('已使用语音转文字', exact=False)).to_be_visible()
                self.assertEqual(self.trial_posts, [dict(url=VIDEO)])
                self.assertEqual(self.protected, [])
                expect(self.page.locator('dialog[open]')).to_have_count(0)
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                shots = Path('.runtime/guest-ai-ui')
                shots.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(shots / f'completed-{width}.png'), full_page=True)

    def test_async_asr_polling_does_not_resubmit(self):
        self.page.clock.install()
        self.next_post.update(status='running', stage='transcribing', summary='', transcript=None, message='正在语音转文字…')
        self.start()
        expect(self.page.get_by_text('正在语音转文字…')).to_be_visible()
        expect(self.page.get_by_role('button', name='处理中…', exact=True)).to_be_disabled()
        self.page.clock.fast_forward(2100)
        expect(self.page.get_by_role('heading', name='游客总结结果')).to_be_visible()
        self.assertEqual(len(self.polls), 1)
        self.assertEqual(len(self.trial_posts), 1)
        self.assertEqual(self.protected, [])

    def test_limit_prompts_login_then_resumes_account_summary(self):
        self.start(VIDEO)
        expect(self.page.get_by_role('heading', name='游客总结结果')).to_be_visible()
        self.available = False
        self.post_error = dict(code='GUEST_AI_LIMIT', detail='游客 AI 体验已用完，请登录后继续')
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill('https://example.com/second-video')
        self.page.get_by_role('button', name='AI 总结', exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('游客 AI 体验已用完')
        self.page.keyboard.press('Escape')
        expect(self.page.get_by_role('dialog')).not_to_be_visible()
        # Repeated clicks on the second video after closing the dialog must always re-open the login dialog.
        self.page.get_by_role('button', name='AI 总结', exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('游客 AI 体验已用完')
        self.assertEqual(self.polls, [])
        self.assertEqual(self.protected, [])
        self.login()
        expect(self.page.get_by_text('登录后的总结', exact=True)).to_be_visible()
        self.assertEqual(self.protected.count('parse'), 1)
        self.assertEqual(self.protected.count('learn/summary'), 1)

    def test_async_duration_limit_prompts_but_passive_restore_does_not(self):
        self.page.clock.install()
        self.next_post.update(status='running', stage='parsing', summary='', transcript=None)
        self.next_poll.update(status='error', stage='error', summary='', error_code='GUEST_AI_TOO_LONG', error='游客体验仅支持 3 分钟以内的视频，请登录后继续')
        self.start()
        self.page.clock.fast_forward(2100)
        expect(self.page.get_by_role('dialog')).to_contain_text('3 分钟')
        self.page.keyboard.press('Escape')
        self.page.reload()
        expect(self.page.get_by_role('heading', name='游客体验视频')).to_be_visible()
        expect(self.page.locator('dialog[open]')).to_have_count(0)
        self.assertEqual(len(self.trial_posts), 1)

    def test_cached_result_restores_and_login_does_not_rerun(self):
        self.available = False
        self.latest = copy.deepcopy(TASK)
        self.latest['summary'] += '\n\n<script>alert("bad")</script><img src=x onerror="alert(1)">'
        self.page.goto(BASE)
        expect(self.page.get_by_role('heading', name='游客总结结果')).to_be_visible()
        expect(self.page.get_by_role('textbox', name='视频链接或分享口令')).to_have_value(VIDEO)
        expect(self.page.locator('.learn-prose script')).to_have_count(0)
        expect(self.page.locator('.learn-prose [onerror]')).to_have_count(0)
        self.page.get_by_role('button', name='登录使用脑图与追问').click()
        self.login()
        expect(self.page.get_by_role('heading', name='游客总结结果')).to_be_visible()
        self.assertEqual(self.trial_posts, [])
        self.assertEqual(self.protected, [])

    def test_uncertain_only_queries_original_task(self):
        self.next_post.update(status='uncertain', stage='error', summary='', transcript=None,
                              error_code='SUBMISSION_UNCERTAIN', error='请勿重复提交，处理状态待核对')
        self.next_poll = copy.deepcopy(self.next_post)
        self.start()
        expect(self.page.get_by_role('alert')).to_contain_text('请勿重复提交')
        self.page.get_by_role('button', name='查看处理状态').click()
        self.page.wait_for_timeout(100)
        self.page.get_by_role('button', name='AI 总结', exact=True).click()
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.trial_posts), 1)
        self.assertEqual(len(self.polls), 2)
        self.assertEqual(self.protected, [])
        expect(self.page.get_by_role('button', name='重试游客总结')).to_have_count(0)

    def test_late_submit_is_discarded_after_input_change(self):
        pending = []
        self.post_handler = lambda route: pending.append(route)
        self.start()
        expect(self.page.get_by_role('button', name='处理中…', exact=True)).to_be_disabled()
        for _ in range(30):
            if pending:
                break
            self.page.wait_for_timeout(20)
        self.assertEqual(len(pending), 1)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill('https://example.com/changed')
        pending[0].fulfill(json=self.next_post)
        self.page.wait_for_timeout(100)
        expect(self.page.get_by_role('heading', name='游客总结结果')).to_have_count(0)
        self.assertEqual(self.polls, [])
        self.assertEqual(self.protected, [])

    def test_passive_restore_does_not_replace_user_input(self):
        pending = []
        self.status_handler = lambda route: pending.append(route)
        self.page.goto(BASE)
        self.page.wait_for_timeout(100)
        self.assertEqual(len(pending), 1)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill('https://example.com/current')
        pending[0].fulfill(json=dict(available=False, max_seconds=180, task=TASK))
        self.page.wait_for_timeout(100)
        expect(self.page.get_by_role('textbox', name='视频链接或分享口令')).to_have_value('https://example.com/current')
        expect(self.page.get_by_role('heading', name='游客总结结果')).to_have_count(0)
        self.assertEqual(self.trial_posts, [])

    def test_failed_cookie_preflight_never_submits_paid_work(self):
        self.status_handler = lambda route: route.fulfill(status=503, json=dict(code='DB_UNAVAILABLE', detail='服务暂不可用'))
        self.start()
        expect(self.page.get_by_role('alert')).to_contain_text('暂时无法确认游客体验状态')
        self.assertEqual(self.trial_posts, [])
        self.assertEqual(self.protected, [])

    def test_no_output_failure_can_retry_without_protected_calls(self):
        self.next_post.update(status='error', stage='error', summary='', transcript=None, retryable=True,
                              error_code='SUMMARY_FAILED', error='没有生成总结，可以重试')
        self.start()
        expect(self.page.get_by_role('button', name='重试游客总结')).to_be_visible()
        self.next_post = copy.deepcopy(TASK)
        self.page.get_by_role('button', name='重试游客总结').click()
        expect(self.page.get_by_role('heading', name='游客总结结果')).to_be_visible()
        self.assertEqual(len(self.trial_posts), 2)
        self.assertEqual(self.protected, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
