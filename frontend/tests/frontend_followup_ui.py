"""A1/A2/A3 browser regressions. Requires Vite on 127.0.0.1:5178.

All APIs and embedded players are mocked; no paid or external service is called.
"""
import json
import re
import unittest
from urllib.parse import parse_qs, quote, urlparse

from playwright.sync_api import expect, sync_playwright


BASE = 'http://127.0.0.1:5178'
USER = dict(id=1, username='tester', nickname='Tester', created_at='2026-11-10T00:00:00Z')
INFO = dict(url='https://example.com/shared-A', title='Follow-up video', platform='Test',
            qualities=[], subtitles=[], duration=300)
SUMMARY = '## Follow-up summary\n\n[01:30] Selected chapter'


class FrontendFollowupUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport=dict(width=1440, height=1000))
        self.errors = []
        self.parsed = []
        self.summaries = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route('**/api/**', lambda r: r.fulfill(json=dict(
            ok=True, ai_enabled=True, asr_enabled=False, plans=[],
            text='Mock transcript', timed_text='[00:01] Mock transcript', cues=[])))
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=USER)))
        self.page.route('**/api/parse', self.parse)
        self.page.route('**/api/learn/summary', self.summarize)
        self.page.route('https://player.bilibili.com/**', lambda r: r.fulfill(
            body='<html><body>Mock Bilibili player</body></html>', content_type='text/html'))

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def parse(self, route):
        url = route.request.post_data_json['url']
        self.parsed.append(url)
        route.fulfill(json={**INFO, 'url': url})

    def summarize(self, route):
        self.summaries.append(route.request.post_data_json)
        route.fulfill(body='event: delta\ndata: ' + json.dumps(SUMMARY) +
                      '\n\nevent: done\ndata: true\n\n', content_type='text/event-stream')

    def test_shared_link_init_respects_latest_action(self):
        for width in (1440, 390):
            for user in (USER, None):
                for action in ('edit', 'clear', 'download', 'leave'):
                    with self.subTest(width=width, logged_in=bool(user), action=action):
                        self.page.set_viewport_size(dict(width=width, height=844))
                        pending = []
                        self.parsed.clear()
                        self.summaries.clear()
                        self.page.route('**/api/auth/me', lambda r: pending.append(r))
                        self.page.goto(BASE + '/?view=ai&url=' + quote(INFO['url'], safe=''))
                        field = self.page.get_by_role('textbox', name='视频链接或分享口令')
                        expect(field).to_be_visible()
                        if action == 'edit':
                            field.fill('https://example.com/user-B')
                        elif action == 'clear':
                            field.fill('https://example.com/user-B')
                            self.page.get_by_role('button', name='清空', exact=True).click()
                        elif action == 'download':
                            self.page.locator('#mode-tab-download').click()
                        else:
                            self.page.locator('section').first.locator('a[href="/pricing"]').first.click()
                            self.page.wait_for_url(BASE + '/pricing')
                        self.assertTrue(pending)
                        for request in pending:
                            request.fulfill(json=dict(user=user))
                        self.page.wait_for_timeout(150)
                        if action != 'leave':
                            self.assertEqual(field.input_value(), 'https://example.com/user-B' if action == 'edit' else '')
                            self.assertEqual(self.page.locator('#mode-tab-download').get_attribute('aria-selected'), 'true')
                        else:
                            self.assertEqual(self.page.url, BASE + '/pricing')
                        self.assertEqual(self.parsed, [])
                        self.assertEqual(self.summaries, [])
                        expect(self.page.locator('dialog[open]')).to_have_count(0)
                        self.page.unroute('**/api/auth/me')

    def test_uninterrupted_shared_link_keeps_auto_parse_and_guest_fallback(self):
        for width in (1440, 390):
            for user in (USER, None):
                with self.subTest(width=width, logged_in=bool(user)):
                    self.page.set_viewport_size(dict(width=width, height=844))
                    pending = []
                    self.parsed.clear()
                    self.summaries.clear()
                    self.page.route('**/api/auth/me', lambda r: pending.append(r))
                    self.page.goto(BASE + '/?view=ai&url=' + quote(INFO['url'], safe=''))
                    expect(self.page.get_by_role('textbox', name='视频链接或分享口令')).to_be_visible()
                    self.assertTrue(pending)
                    for request in pending:
                        request.fulfill(json=dict(user=user))
                    if user:
                        expect(self.page.locator('.learn-prose').first).to_contain_text('Follow-up summary')
                    else:
                        expect(self.page.get_by_text(INFO['title'], exact=True).first).to_be_visible()
                    self.assertEqual(self.parsed, [INFO['url']])
                    self.assertEqual(len(self.summaries), 1 if user else 0)
                    selected = '#mode-tab-ai' if user else '#mode-tab-download'
                    expect(self.page.locator(selected)).to_have_attribute('aria-selected', 'true')
                    expect(self.page.locator('dialog[open]')).to_have_count(0)
                    self.page.unroute('**/api/auth/me')

    def test_bilibili_part_survives_preview_mode_and_timestamp_seek(self):
        for width in (1440, 390):
            for path in ('/', '/learn'):
                for part in (2, 3):
                    with self.subTest(width=width, path=path, part=part):
                        self.page.set_viewport_size(dict(width=width, height=844))
                        video = f'https://www.bilibili.com/video/BV1mAAmzqEfP/?p={part}'
                        self.page.goto(BASE + path)
                        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(video)
                        self.page.locator('form button[type="submit"]').first.click()
                        frame = self.page.locator('iframe[src*="player.bilibili.com"]').first
                        expect(frame).to_be_visible()
                        query = parse_qs(urlparse(frame.get_attribute('src')).query)
                        self.assertEqual(query.get('p'), [str(part)])
                        self.assertEqual(query.get('t'), ['0'])
                        self.assertEqual(query.get('autoplay'), ['0'])
                        if path == '/':
                            self.page.locator('#mode-tab-ai').click()
                            expect(frame).to_be_visible()
                            self.page.get_by_role('button', name='AI 总结', exact=True).click()
                        else:
                            self.page.get_by_role('button', name='一键 AI 总结', exact=True).click()
                        self.page.locator('button[data-seek="90"]').first.click()
                        expect(frame).to_have_attribute('src', re.compile(r'[?&]t=90(?:&|$)'))
                        query = parse_qs(urlparse(frame.get_attribute('src')).query)
                        self.assertEqual(query.get('p'), [str(part)])
                        self.assertEqual(query.get('autoplay'), ['1'])
                        self.assertEqual(query.get('bvid'), ['BV1mAAmzqEfP'])

    def test_old_auth_failure_does_not_interrupt_new_login(self):
        pending = []
        next_user = {**USER, 'id': 2, 'nickname': 'New Tester'}
        self.page.route('**/api/account/history?*', lambda r: pending.append(r))
        self.page.route('**/api/auth/login', lambda r: r.fulfill(json=dict(user=next_user)))
        self.page.goto(BASE)
        self.page.evaluate("""async () => {
            const {account, accountApi} = await import('/src/account.js');
            await account.ensure();
            window.oldHistory = accountApi.history({page: 1}).catch(error => error.code);
        }""")
        self.page.wait_for_timeout(50)
        self.assertEqual(len(pending), 1)
        self.page.evaluate("""async () => {
            const {account} = await import('/src/account.js');
            await account.login({email: 'new@example.com', password: 'password123'});
        }""")
        pending[0].fulfill(status=401, json=dict(detail='Expired old session', code='AUTH_REQUIRED'))
        self.assertEqual(self.page.evaluate('() => window.oldHistory'), 'AUTH_REQUIRED')
        state = self.page.evaluate("async () => {const {account}=await import('/src/account.js');return {id:account.user?.id,status:account.status}}")
        self.assertEqual(state, dict(id=2, status='authed'))
        expect(self.page.locator('dialog[open]')).to_have_count(0)
        expect(self.page.locator('nav').get_by_role('button', name='New Tester', exact=True)).to_be_visible()


if __name__ == '__main__':
    unittest.main(verbosity=2)
