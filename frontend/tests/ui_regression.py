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
                    self.page.get_by_role('button', name='字幕翻译', exact=True).click()
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
        self.page.goto(BASE)
        opener = self.page.get_by_role('button', name='登录', exact=True)
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
