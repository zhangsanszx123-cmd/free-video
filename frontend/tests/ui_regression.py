"""Browser regression checks. Run with an existing Python Playwright installation.

Start Vite on 127.0.0.1:5178, then: python -P frontend/tests/ui_regression.py
All API calls are mocked; no platform downloads or paid AI requests are made.
"""
import unittest
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:5178'
INFO = dict(url='https://example.com/video', title='回归测试视频', platform='Test',
            qualities=[dict(height=720, label='720P')], subtitles=[], duration=60)


class UIRegression(unittest.TestCase):
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
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.route('**/api/**', lambda r: r.fulfill(json=dict(
            ok=True, ai_enabled=True, asr_enabled=False, text='字幕', timed_text='[00:01] 字幕')))
        # /batch, /ai and /learn require login; account flows are covered by account_ui.py.
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=dict(
            id=1, username='tester', nickname='测试用户', created_at='2026-11-10T00:00:00Z'))))
        self.page.route('**/api/plans', lambda r: r.fulfill(json=dict(plans=[
            dict(code='free', name='免费用户', price_cents=0, monthly_seconds=1800),
            dict(code='monthly', name='月卡会员', price_cents=1990, monthly_seconds=36000),
            dict(code='yearly', name='年卡会员', price_cents=9900, monthly_seconds=108000)])))
        self.page.route('**/api/auth/captcha', lambda r: r.fulfill(json=dict(id='ui-test', image='data:image/png;base64,iVBORw0KGgo=', expires_in=300)))

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def test_clear_pending_parse(self):
        for path, button in [('/', '立即解析'), ('/learn', '进入学习工作台')]:
            with self.subTest(path=path):
                pending = []
                self.page.route('**/api/parse', lambda r: pending.append(r))
                self.page.goto(BASE + path)
                self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
                self.page.get_by_role('button', name=button, exact=True).click()
                self.page.wait_for_timeout(100)
                self.assertEqual(len(pending), 1)
                self.page.get_by_role('button', name='清空', exact=True).click()
                pending[0].fulfill(json=INFO)
                self.page.wait_for_timeout(100)
                expect(self.page.get_by_text(INFO['title'], exact=True)).to_have_count(0)
                expect(self.page.get_by_role('textbox', name='视频链接或分享口令')).to_have_value('')
                self.page.unroute('**/api/parse')

    def test_submission_locks(self):
        for path, endpoint, button in [('/batch', 'batch', '开始批量下载（1 条）'),
                                       ('/ai', 'ai/translate', '生成双语字幕')]:
            with self.subTest(path=path):
                pending = []
                self.page.route('**/api/' + endpoint, lambda r: pending.append(r))
                self.page.goto(BASE + path)
                if path == '/batch':
                    self.page.get_by_label('\u4e0b\u8f7d\u683c\u5f0f').select_option('video')
                if path == '/ai':
                    self.page.get_by_role('tab', name='字幕翻译', exact=True).click()
                self.page.get_by_role('textbox').fill(INFO['url'])
                control = self.page.get_by_role('button', name=button, exact=True).element_handle()
                control.evaluate('(b) => { b.click(); b.click(); }')
                self.page.wait_for_timeout(100)
                self.assertEqual(len(pending), 1)
                self.assertTrue(control.is_disabled())
                pending[0].fulfill(status=400, json=dict(detail='测试失败，请重试'))
                self.page.wait_for_function('(b) => !b.disabled', arg=control)
                expect(self.page.get_by_role('alert')).to_contain_text('测试失败')

    def test_video_audio_submission_locks(self):
        self.page.route('**/api/parse', lambda r: r.fulfill(json=INFO))
        pending = []
        self.page.route('**/api/download', lambda r: pending.append(r))
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        self.page.get_by_role('button', name='立即解析', exact=True).click()
        for name in ['下载高清视频', '下载音频']:
            control = self.page.get_by_role('button', name=name, exact=True).element_handle()
            control.evaluate('(b) => { b.click(); b.click(); }')
            self.page.wait_for_timeout(100)
            self.assertTrue(control.is_disabled())
        self.assertEqual(len(pending), 2)
        for route in pending:
            route.fulfill(status=400, json=dict(detail='下载提交失败'))
        expect(self.page.get_by_role('button', name='下载高清视频', exact=True)).to_be_enabled()
        expect(self.page.get_by_role('button', name='下载音频', exact=True)).to_be_enabled()

    def test_health_failure(self):
        self.page.route('**/api/health', lambda r: r.fulfill(status=503, json={}))
        self.page.goto(BASE)
        expect(self.page.get_by_role('status')).to_contain_text('服务连接失败')

    def test_video_zip_error_and_retry(self):
        from io import BytesIO
        import zipfile
        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('video.mp4', b'test')
        job = dict(id='archive-test', status='done', progress=100, ready=True, filename='batch.zip')
        self.page.route('**/api/batch', lambda r: r.fulfill(json=job))
        metadata_error = [False]
        self.page.route('**/api/jobs/archive-test', lambda r: r.fulfill(status=404, json=dict(detail='文件已过期')) if metadata_error[0] else r.fulfill(json=job))
        self.page.route('**/api/jobs/archive-test/file*', lambda r: r.fulfill(body=archive.getvalue(), content_type='application/zip', headers={'Content-Disposition': 'attachment; filename=test.zip'}))
        self.page.goto(BASE + '/batch')
        self.page.get_by_label('下载格式').select_option('video')
        self.page.get_by_role('textbox').fill(INFO['url'])
        self.page.get_by_role('button', name='开始批量下载（1 条）').click()
        save = self.page.get_by_role('button', name='保存到本地', exact=False)
        expect(save).to_be_visible()
        self.page.wait_for_timeout(100)
        metadata_error[0] = True
        self.page.evaluate("""() => {
          const originalFetch = window.fetch;
          window.fetch = (...args) => {
            if (String(args[0]).includes('/file')) throw new Error('File transfer must not use fetch');
            return originalFetch(...args);
          };
        }""")
        save.click()
        expect(self.page.get_by_role('alert')).to_contain_text('文件已过期')
        metadata_error[0] = False
        with self.page.expect_download() as event:
            save.click()
        # Mocked navigation validates handoff; real ZIP integrity is checked against the live server.
        self.assertIn('/api/jobs/archive-test/file', event.value.url)

    def test_dialog_keyboard(self):
        # The nav "登录" entry is now a real login link; the pricing purchase button still opens the demo dialog.
        self.page.goto(BASE + '/pricing')
        opener = self.page.get_by_role('button', name='开通月卡', exact=True)
        opener.click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        self.assertTrue(self.page.evaluate('document.activeElement.closest("dialog") !== null'))
        for _ in range(5):
            self.page.keyboard.press('Tab')
            self.assertTrue(self.page.evaluate('document.activeElement.closest("dialog") !== null'))
        self.page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(opener).to_be_focused()
        self.assertEqual(self.page.evaluate('document.body.style.overflow'), '')

    def test_mobile_layout(self):
        self.page.set_viewport_size(dict(width=390, height=844))
        for path in ['/', '/learn', '/batch', '/ai', '/pricing']:
            self.page.goto(BASE + path)
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.goto(BASE)
        close = self.page.get_by_role('button', name='关闭升级提示')
        bounds = close.bounding_box()
        self.assertGreaterEqual(bounds['width'], 44)
        self.assertGreaterEqual(bounds['height'], 44)
        self.assertGreater(float(self.page.evaluate('parseFloat(getComputedStyle(document.body).paddingBottom)')), 0)
        close.click()
        self.assertEqual(self.page.evaluate('parseFloat(getComputedStyle(document.body).paddingBottom)'), 0)


    def test_copy_and_marketing_rules(self):
        """Copy must match current rules: no PRO badges / "limited free" / 8K / ad claims; FAQ mentions ASR."""
        banned = ['限时免费', '8K', '广告与插件', '按量计费', '付费语音识别', 'API 预算']
        for path in ['/', '/batch', '/ai', '/learn', '/pricing']:
            self.page.goto(BASE + path)
            self.page.wait_for_timeout(150)
            body = self.page.inner_text('body')
            for word in banned:
                self.assertNotIn(word, body, f'{word} on {path}')
            self.assertEqual(self.page.get_by_text('PRO', exact=True).count(), 0, path)
        self.page.goto(BASE)
        faq = self.page.get_by_role('button', name='AI 总结是怎么实现的？')
        faq.click()
        expect(self.page.get_by_text('可在你确认后先用语音识别生成文稿', exact=False)).to_be_visible()
        self.page.goto(BASE + '/batch')
        expect(self.page.get_by_text('消耗你的每月语音识别额度')).to_be_visible()

    def test_ai_copy_failure_is_handled(self):
        self.page.route('**/api/ai/summary', lambda r: r.fulfill(
            body='event: delta\ndata: "hi"\n\n', content_type='text/event-stream'))
        self.page.goto(BASE + '/ai')
        self.page.get_by_role('textbox').fill(INFO['url'])
        self.page.get_by_role('button', name='开始总结', exact=True).click()
        copy = self.page.get_by_role('button', name='复制', exact=True)
        expect(copy).to_be_visible()
        self.page.evaluate('() => { navigator.clipboard.writeText = () => Promise.reject(new Error("denied")); }')
        copy.click()
        expect(self.page.get_by_text('复制失败')).to_be_visible()

    def test_mobile_menu_escape_and_account_menu(self):
        self.page.set_viewport_size(dict(width=390, height=844))
        self.page.goto(BASE)
        toggle = self.page.get_by_role('button', name='打开导航菜单')
        toggle.click()
        self.page.wait_for_timeout(400)
        expect(self.page.locator('#mobile-navigation')).to_be_visible()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#mobile-navigation')).to_have_count(0)
        expect(self.page.get_by_role('button', name='打开导航菜单')).to_be_focused()
        self.page.set_viewport_size(dict(width=1440, height=900))
        self.page.locator('button[aria-haspopup=menu]').click()
        menu = self.page.get_by_role('menu')
        expect(menu.get_by_role('menuitem', name=r'个人中心', exact=False)).to_have_count(1)
        self.page.keyboard.press('Escape')
        expect(menu).to_have_count(0)
        expect(self.page.locator('button[aria-haspopup=menu]')).to_be_focused()

    def test_result_card_no_duplicate_controls(self):
        self.page.route('**/api/parse', lambda r: r.fulfill(json=dict(INFO, thumbnail='https://example.invalid/t.jpg')))
        self.page.route('**/example.invalid/**', lambda r: r.abort())
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        self.page.get_by_role('button', name='立即解析', exact=True).click()
        expect(self.page.get_by_role('button', name='下载高清视频', exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_role('button', name='复制全部链接').count(), 0)
        self.assertEqual(self.page.get_by_role('button', name='下载视频', exact=True).count(), 0)
        expect(self.page.get_by_role('heading', name='封面图片')).to_be_visible()
        expect(self.page.get_by_text('暂无可预览的音频')).to_be_visible()
        panel = self.page.get_by_role('tabpanel')
        expect(panel).to_be_visible()
        expect(self.page.get_by_role('tab', name='素材与文案下载')).to_have_attribute('aria-controls', 'result-panel')

    def test_not_found_page(self):
        self.page.goto(BASE + '/no-such-page')
        expect(self.page.get_by_role('heading', name='没有找到这个页面')).to_be_visible()
        self.page.get_by_role('link', name='返回首页').click()
        self.page.wait_for_url(BASE + '/')

    def test_account_defaults_to_membership(self):
        self.page.route('**/api/account/membership', lambda r: r.fulfill(json=dict(
            plan='free', name='免费用户', limit_seconds=1800, used_seconds=0, reserved_seconds=0, available_seconds=1800,
            resets_at='2026-12-10T00:00:00Z', ends_with_membership=False, payment_enabled=True)))
        self.page.route('**/api/pay/orders', lambda r: r.fulfill(json=dict(orders=[])))
        self.page.goto(BASE + '/account')
        nav = self.page.get_by_role('navigation', name='个人中心分区')
        expect(nav.get_by_role('button', name='会员与额度')).to_have_attribute('aria-current', 'page')
        expect(self.page.get_by_role('region', name='语音识别额度')).to_be_visible()

    MEMBER = dict(plan='free', name='免费用户', limit_seconds=1800, used_seconds=0, reserved_seconds=0, available_seconds=1800,
                  resets_at='2026-12-10T00:00:00Z', ends_with_membership=False, payment_enabled=True, ai_limit=10, ai_used=10,
                  chat_daily_limit=20, chat_used_today=3, batch_max_links=3, asr_max_minutes=30)

    def test_plan_limits_are_shown(self):
        limits = dict(ai_monthly_limit=10, batch_max_links=3, asr_max_minutes=30, chat_daily_limit=20)
        self.page.route('**/api/plans', lambda r: r.fulfill(json=dict(payment_enabled=True, plans=[
            dict(code='free', name='免费用户', price_cents=0, monthly_seconds=1800, **limits),
            dict(code='monthly', name='月卡会员', price_cents=1990, monthly_seconds=36000, ai_monthly_limit=300,
                 batch_max_links=10, asr_max_minutes=60, chat_daily_limit=100),
            dict(code='yearly', name='年卡会员', price_cents=9900, monthly_seconds=108000, ai_monthly_limit=500,
                 batch_max_links=15, asr_max_minutes=120, chat_daily_limit=200)])))
        self.page.route('**/api/account/membership', lambda r: r.fulfill(json=self.MEMBER))
        self.page.route('**/api/pay/orders', lambda r: r.fulfill(json=dict(orders=[])))
        self.page.goto(BASE + '/pricing')
        cards = self.page.locator('article')
        expect(cards.nth(0)).to_contain_text('AI 视频总结每月 10 个视频')
        expect(cards.nth(1)).to_contain_text('批量提取单次最多 10 条链接')
        expect(cards.nth(2)).to_contain_text('单条语音识别最长 120 分钟')
        row = self.page.get_by_role('row', name='AI 追问（每天）')
        expect(row).to_contain_text('20 条')
        expect(row).to_contain_text('200 条')
        self.page.goto(BASE + '/account')
        quota = self.page.get_by_role('region', name='语音识别额度')
        expect(quota).to_contain_text('本期已用 10 / 10 个视频')
        expect(quota).to_contain_text('今日已用 3 / 20 条')
        expect(quota).to_contain_text('单次最多 3 条')

    def test_batch_cap_follows_plan_and_blocks_submit(self):
        self.page.route('**/api/account/membership', lambda r: r.fulfill(json=self.MEMBER))
        posted = []
        self.page.route('**/api/batch', lambda r: posted.append(r))
        self.page.goto(BASE + '/batch')
        self.page.get_by_label('下载格式').select_option('video')
        self.page.get_by_role('textbox').fill('https://a.com/1 https://a.com/2 https://a.com/3 https://a.com/4')
        expect(self.page.get_by_text('免费用户单次最多 3 条 · 自动去重')).to_be_visible()
        expect(self.page.get_by_text('/ 3 条链接')).to_be_visible()
        self.page.get_by_role('button', name='开始批量下载（4 条）').click()
        expect(self.page.get_by_role('alert')).to_contain_text('单次最多 3 条')
        expect(self.page.get_by_role('link', name='升级提高上限')).to_be_visible()
        self.assertEqual(posted, [])

    def test_ai_limit_message_is_shown(self):
        self.page.route('**/api/parse', lambda r: r.fulfill(json=INFO))
        self.page.route('**/api/learn/summary', lambda r: r.fulfill(
            body='event: error\ndata: "本期 AI 次数已用完（10/10 个视频）。"\n\n', content_type='text/event-stream'))
        self.page.goto(BASE + '/learn?url=' + INFO['url'])
        self.page.get_by_role('button', name='一键 AI 总结').click()
        expect(self.page.get_by_text('本期 AI 次数已用完')).to_be_visible()

    def test_guest_extracts_subtitles_within_allowance(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        calls = []
        self.page.route('**/api/transcript', lambda r: (calls.append(r.request.url), r.fulfill(
            json=dict(text='游客免费提取的字幕内容', timed_text='[00:01] 游客免费提取的字幕内容', srt='1\n00:00:00,000 --> 00:00:01,000\n游客免费提取的字幕内容\n', cues=1, source='platform_subtitle')))[0])
        self.page.route('**/api/parse', lambda r: r.fulfill(json=dict(INFO, subtitles=[dict(lang='zh', name='中文')])))
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        self.page.get_by_role('button', name='立即解析', exact=True).click()
        expect(self.page.get_by_text('游客免费提取的字幕内容')).to_be_visible()
        expect(self.page.get_by_role('button', name='下载高清视频', exact=True)).to_be_enabled()
        self.assertEqual(len(calls), 1)

    def mock_home_ai_actions(self):
        calls = dict(parse=[], summary=[], transcription=[])

        def parse(route):
            url = route.request.post_data_json['url']
            calls['parse'].append(url)
            route.fulfill(json=dict(INFO, url=url))

        def summarize(route):
            calls['summary'].append(route.request.post_data_json)
            route.fulfill(body='event: delta\ndata: "Mock home summary"\n\nevent: done\ndata: true\n\n',
                          content_type='text/event-stream')

        def transcribe(route):
            calls['transcription'].append(route.request.url)
            route.fulfill(json=dict(text='Mock transcript', timed_text='[00:01] Mock transcript', cues=[]))

        self.page.route('**/api/parse', parse)
        self.page.route('**/api/learn/summary', summarize)
        self.page.route('**/api/transcri**', transcribe)
        return calls

    def test_guest_home_ai_tab_only_previews_mode(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        calls = self.mock_home_ai_actions()
        for width in (1440, 390):
            for state in ('empty', 'populated', 'existing_result'):
                with self.subTest(width=width, state=state):
                    calls['parse'].clear()
                    calls['summary'].clear()
                    calls['transcription'].clear()
                    self.page.set_viewport_size(dict(width=width, height=1000))
                    self.page.goto(BASE)
                    url = self.page.get_by_role('textbox', name='视频链接或分享口令')
                    if state != 'empty':
                        url.fill(INFO['url'])
                    if state == 'existing_result':
                        self.page.get_by_role('button', name='立即解析', exact=True).click()
                        expect(self.page.get_by_role('heading', name='提取结果', exact=True)).to_be_visible()
                        self.assertEqual(calls['parse'], [INFO['url']])
                    before = {key: list(value) for key, value in calls.items()}
                    ai_tab = self.page.get_by_role('tab', name='AI 视频总结', exact=True)
                    ai_tab.click()
                    expect(ai_tab).to_have_attribute('aria-selected', 'true')
                    expect(self.page.get_by_role('button', name='AI 总结', exact=True)).to_be_visible()
                    expect(url).to_have_value('' if state == 'empty' else INFO['url'])
                    self.page.wait_for_timeout(150)
                    expect(self.page.locator('dialog[open]')).to_have_count(0)
                    self.assertEqual(calls, before, 'Selecting the AI tab must only preview the mode')

    def test_exhausted_guest_home_ai_primary_submit_resumes_once_after_login(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        user = dict(id=1, username='tester', nickname='Tester', created_at='2026-11-10T00:00:00Z')
        self.page.route('**/api/auth/login', lambda r: r.fulfill(json=dict(user=user)))
        self.page.route('**/api/account/membership', lambda r: r.fulfill(json=self.MEMBER))
        self.page.route('**/api/guest/ai-summary', lambda r: r.fulfill(
            status=403 if r.request.method == 'POST' else 200,
            json=dict(detail='游客 AI 体验已用完，请登录后继续', code='GUEST_AI_LIMIT') if r.request.method == 'POST' else dict(available=False, max_seconds=180, task=None)))
        calls = self.mock_home_ai_actions()
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        self.page.get_by_role('tab', name='AI 视频总结', exact=True).click()
        expect(self.page.locator('dialog[open]')).to_have_count(0)
        self.page.get_by_role('button', name='AI 总结', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('游客 AI 体验已用完，请登录后继续')
        self.assertEqual(calls, dict(parse=[], summary=[], transcription=[]))
        dialog.get_by_label('邮箱', exact=True).fill('tester@example.com')
        dialog.get_by_label('密码', exact=True).fill('password123')
        dialog.get_by_role('button', name='登录', exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(self.page.get_by_text('Mock home summary', exact=True)).to_be_visible()
        self.page.wait_for_timeout(150)
        self.assertEqual(calls['parse'], [INFO['url']])
        self.assertEqual([body['url'] for body in calls['summary']], [INFO['url']])
        self.assertEqual(calls['transcription'], [])
        expect(self.page.get_by_role('tab', name='AI 视频总结', exact=True)).to_have_attribute('aria-selected', 'true')
        self.assertEqual(self.page.url, BASE + '/')

    def test_home_ai_pending_auth_is_discarded_after_tab_or_input_change(self):
        calls = self.mock_home_ai_actions()
        for action in ('tab', 'edit'):
            for logged_in in (False, True):
                with self.subTest(action=action, logged_in=logged_in):
                    pending = []
                    for value in calls.values():
                        value.clear()
                    self.page.route('**/api/auth/me', lambda r: pending.append(r))
                    self.page.goto(BASE)
                    url = self.page.get_by_role('textbox', name='视频链接或分享口令')
                    url.fill(INFO['url'])
                    ai_tab = self.page.get_by_role('tab', name='AI 视频总结', exact=True)
                    ai_tab.click()
                    expect(ai_tab).to_have_attribute('aria-selected', 'true')
                    self.page.get_by_role('button', name='AI 总结', exact=True).click()
                    self.assertTrue(pending)
                    if action == 'tab':
                        # Both mode tabs only switch views; parsing begins only at the submit button.
                        self.page.get_by_role('tab', name='素材与文案下载', exact=True).click()
                        ai_tab.click()
                    else:
                        url.fill('https://example.com/changed')
                    user = dict(id=1, username='tester', nickname='Tester', created_at='2026-11-10T00:00:00Z') if logged_in else None
                    for request in pending:
                        request.fulfill(json=dict(user=user))
                    self.page.wait_for_timeout(150)
                    expect(self.page.locator('dialog[open]')).to_have_count(0)
                    expect(ai_tab).to_have_attribute('aria-selected', 'true')
                    self.assertEqual(calls['parse'], [])
                    self.assertEqual(calls['summary'], [])
                    self.assertEqual(calls['transcription'], [])
                    self.page.unroute('**/api/auth/me')

    def test_home_ai_tab_round_trip_during_parse_does_not_start_summary(self):
        calls = self.mock_home_ai_actions()
        pending = []
        self.page.route('**/api/parse', lambda r: pending.append(r))
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        ai_tab = self.page.get_by_role('tab', name='AI 视频总结', exact=True)
        ai_tab.click()
        self.page.get_by_role('button', name='AI 总结', exact=True).click()
        expect(self.page.get_by_role('button', name='解析中…', exact=True)).to_be_disabled()
        self.assertEqual(len(pending), 1)
        self.page.get_by_role('tab', name='素材与文案下载', exact=True).click()
        ai_tab.click()
        pending[0].fulfill(json=INFO)
        expect(self.page.get_by_role('button', name='一键 AI 总结', exact=True)).to_be_visible()
        self.page.wait_for_timeout(150)
        self.assertEqual(calls['summary'], [])
        self.assertEqual(calls['transcription'], [])
        expect(ai_tab).to_have_attribute('aria-selected', 'true')
        expect(self.page.locator('dialog[open]')).to_have_count(0)

    def test_home_download_parse_does_not_reuse_previous_ai_trigger(self):
        calls = self.mock_home_ai_actions()
        self.page.goto(BASE)
        url = self.page.get_by_role('textbox', name='视频链接或分享口令')
        url.fill(INFO['url'])
        ai_tab = self.page.get_by_role('tab', name='AI 视频总结', exact=True)
        ai_tab.click()
        self.page.get_by_role('button', name='AI 总结', exact=True).click()
        expect(self.page.get_by_text('Mock home summary', exact=True)).to_be_visible()
        self.assertEqual(len(calls['summary']), 1)
        self.page.get_by_role('tab', name='素材与文案下载', exact=True).click()
        changed_url = 'https://example.com/another-video'
        url.fill(changed_url)
        self.page.get_by_role('tab', name='素材与文案下载', exact=True).click()
        self.page.wait_for_timeout(150)
        self.assertEqual(calls['parse'], [INFO['url']], 'Selecting the download tab must not auto-parse')
        self.page.get_by_role('button', name='立即解析', exact=True).click()
        expect(self.page.get_by_role('button', name='下载高清视频', exact=True)).to_be_visible()
        self.page.wait_for_timeout(150)
        self.assertEqual(calls['parse'], [INFO['url'], changed_url])
        self.assertEqual(len(calls['summary']), 1, 'A new download parse must not replay the old AI trigger')
        ai_tab.click()
        expect(self.page.get_by_role('button', name='一键 AI 总结', exact=True)).to_be_visible()
        self.page.wait_for_timeout(150)
        self.assertEqual(len(calls['summary']), 1, 'Previewing the newly parsed video must not start a summary')
        self.assertEqual(calls['transcription'], [])

    def test_guest_limit_opens_login_dialog(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        parse_calls = []
        self.page.route('**/api/parse', lambda r: (parse_calls.append(r.request.url), r.fulfill(status=403, json=dict(
            detail='游客的 2 个视频名额已用完，请登录后继续', code='GUEST_LIMIT')))[0])
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        self.page.get_by_role('tab', name='AI 视频总结', exact=True).click()
        self.page.get_by_role('tab', name='素材与文案下载', exact=True).click()
        self.page.wait_for_timeout(150)
        self.assertEqual(parse_calls, [], 'Switching to the download tab must never auto-parse or prompt login')
        expect(self.page.locator('dialog[open]')).to_have_count(0)
        self.page.get_by_role('button', name='立即解析', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('名额已用完')
        expect(self.page.get_by_role('alert').first).to_contain_text('名额已用完')

    def test_batch_login_refreshes_limits_before_resuming(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        user = dict(id=1, username='tester', nickname='Tester', created_at='2026-11-10T00:00:00Z')
        self.page.route('**/api/auth/login', lambda r: r.fulfill(json=dict(user=user)))
        pending = []
        posted = []
        self.page.route('**/api/account/membership', lambda r: pending.append(r))
        self.page.route('**/api/batch', lambda r: (posted.append(r.request.url), r.fulfill(json=dict(id='test', status='done')))[0])
        self.page.goto(BASE + '/batch')
        self.page.get_by_label('下载格式').select_option('video')
        self.page.get_by_role('textbox').fill(' '.join(f'https://a.com/{i}' for i in range(4)))
        self.page.get_by_role('button', name='开始批量下载（4 条）').click()
        dialog = self.page.get_by_role('dialog')
        dialog.get_by_label('邮箱', exact=True).fill('tester@example.com')
        dialog.get_by_label('密码', exact=True).fill('password123')
        dialog.get_by_role('button', name='登录', exact=True).click()
        expect(dialog).not_to_be_visible()
        self.page.wait_for_timeout(150)
        self.assertEqual(posted, [], 'Must wait for account limits before submitting')
        self.assertEqual(len(pending), 1)
        pending.pop().fulfill(json=self.MEMBER)
        expect(self.page.get_by_text('免费用户单次最多 3 条 · 自动去重')).to_be_visible()
        expect(self.page.get_by_role('alert')).to_contain_text('单次最多 3 条')
        self.assertEqual(posted, [])

    def test_auth_check_does_not_resume_after_navigation_or_edit(self):
        for path, button in [('/batch', '开始批量下载（1 条）'), ('/ai', '开始总结'),
                             ('/learn', '进入学习工作台')]:
            for action in ('navigate', 'edit', 'navigate_authed', 'edit_authed'):
                with self.subTest(path=path, action=action):
                    pending = []
                    posted = []
                    self.page.route('**/api/auth/me', lambda r: pending.append(r))
                    for endpoint in ('batch', 'ai/summary', 'parse'):
                        self.page.route('**/api/' + endpoint, lambda r: (posted.append(r.request.url), r.abort())[0])
                    self.page.goto(BASE + path)
                    if path == '/batch':
                        self.page.get_by_label('下载格式').select_option('video')
                    self.page.get_by_role('textbox').first.fill(INFO['url'])
                    self.page.get_by_role('button', name=button, exact=True).click()
                    if action.startswith('navigate'):
                        self.page.get_by_role('link', name='定价', exact=True).first.click()
                        self.page.wait_for_url(BASE + '/pricing')
                    else:
                        # Simulate an input event already queued when the check began.
                        self.page.get_by_role('textbox').first.evaluate("el => { el.value = 'https://example.com/changed'; el.dispatchEvent(new Event('input', {bubbles:true})) }")
                    self.assertTrue(pending)
                    user = dict(id=1, username='tester', nickname='Tester', created_at='2026-11-10T00:00:00Z') if action.endswith('_authed') else None
                    for request in pending:
                        request.fulfill(json=dict(user=user))
                    self.page.wait_for_timeout(150)
                    expect(self.page.get_by_role('dialog')).not_to_be_visible()
                    self.assertEqual(posted, [])
                    self.page.unroute('**/api/auth/me')

    def test_batch_membership_failure_can_retry_without_submitting(self):
        self.page.route('**/api/account/membership', lambda r: r.fulfill(status=503, json=dict(detail='membership unavailable')))
        posted = []
        self.page.route('**/api/batch', lambda r: (posted.append(r.request.url), r.fulfill(json=dict(id='test', status='done')))[0])
        self.page.goto(BASE + '/batch')
        self.page.get_by_label('下载格式').select_option('video')
        self.page.get_by_role('textbox').fill(INFO['url'])
        self.page.get_by_role('button', name='开始批量下载（1 条）').click()
        expect(self.page.get_by_role('alert')).to_contain_text('membership unavailable')
        self.assertEqual(posted, [])
        self.page.route('**/api/account/membership', lambda r: r.fulfill(json=self.MEMBER))
        self.page.get_by_role('button', name='开始批量下载（1 条）').click()
        expect(self.page.get_by_text('免费用户单次最多 3 条 · 自动去重')).to_be_visible()
        self.page.wait_for_timeout(150)
        self.assertEqual(len(posted), 1)

    def test_guest_can_open_ai_and_batch_pages_and_is_asked_on_action(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        posted = []
        for endpoint in ('batch', 'ai/translate', 'ai/summary', 'parse'):
            self.page.route('**/api/' + endpoint, lambda r: (posted.append(r), r.abort())[0])
        for path, url_box, button in (('/batch', None, '开始批量下载（1 条）'), ('/ai', None, '开始总结'),
                                      ('/learn', None, '进入学习工作台')):
            self.page.goto(BASE + path)
            expect(self.page.get_by_role('dialog')).to_have_count(0)
            self.assertEqual(self.page.url, BASE + path)
            if path == '/batch':
                self.page.get_by_label('下载格式').select_option('video')
            self.page.get_by_role('textbox').first.fill(INFO['url'])
            self.page.get_by_role('button', name=button, exact=True).click()
            expect(self.page.get_by_role('dialog')).to_be_visible()
            self.page.keyboard.press('Escape')
            expect(self.page.get_by_role('dialog')).not_to_be_visible()
        self.assertEqual(posted, [])

    def test_seo_meta_canonical_robots_and_json_ld(self):
        self.page.goto(BASE + '/')
        self.assertIn('在线视频文案提取', self.page.title())
        desc = self.page.locator('meta[name="description"]').get_attribute('content')
        keywords = self.page.locator('meta[name="keywords"]').get_attribute('content')
        robots = self.page.locator('meta[name="robots"]').get_attribute('content')
        canonical = self.page.locator('link[rel="canonical"]').get_attribute('href')
        self.assertIn('视频文案提取', desc)
        self.assertIn('视频转文字', keywords)
        self.assertIn('index, follow', robots)
        self.assertEqual(canonical, BASE + '/')
        schemas = self.page.evaluate("""() => Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => JSON.parse(s.textContent)['@type'])""")
        self.assertEqual(schemas, ['WebSite', 'Organization', 'WebPage', 'SoftwareApplication', 'HowTo', 'BreadcrumbList', 'FAQPage'])
        self.page.goto(BASE + '/batch')
        expect(self.page).to_have_title('批量视频文案提取与素材打包下载 - 在线批量字幕转文字工具 - FreeVideo')
        self.assertEqual(self.page.locator('link[rel="canonical"]').get_attribute('href'), BASE + '/batch')
        self.assertIn('index, follow', self.page.locator('meta[name="robots"]').get_attribute('content'))
        self.page.goto(BASE + '/no-such-page')
        expect(self.page).to_have_title('页面不存在 - FreeVideo')
        self.assertEqual(self.page.locator('meta[name="robots"]').get_attribute('content'), 'noindex, nofollow')


if __name__ == '__main__':
    unittest.main(verbosity=2)
