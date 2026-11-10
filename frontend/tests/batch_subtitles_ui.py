"""Mocked browser checks; Vite must be running on 127.0.0.1:5178."""
from pathlib import Path
from io import BytesIO
import zipfile
import unittest
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:5178'
ZIP_BUFFER = BytesIO()
with zipfile.ZipFile(ZIP_BUFFER, 'w') as archive:
    archive.writestr('sample.srt', 'subtitle')
ZIP_BYTES = ZIP_BUFFER.getvalue()
ID = 'a' * 32
URLS = ['https://example.com/1', 'https://example.com/2', 'https://example.com/3']
RESULT = dict(text='这是完整的字幕正文。', timed_text='[00:01] 这是完整的字幕正文。',
              srt='1\n00:00:01,000 --> 00:00:03,000\n这是完整的字幕正文。\n', cues=1, source='platform_subtitle')


def snapshot(done=False):
    items = [dict(url=URLS[0], title='平台字幕示例', status='done', stage='done', result=RESULT, error=None),
             dict(url=URLS[1], title='语音识别示例', status='done' if done else 'running', stage='done' if done else 'recognizing',
                  result={**RESULT, 'source': 'asr'} if done else None, error=None, message='云端语音识别中'),
             dict(url=URLS[2], title='失败示例', status='error', stage='error', result=None, error='字幕需要登录后访问')]
    return dict(id=ID, status='done' if done else 'running', total=3, completed=3 if done else 2,
                succeeded=2 if done else 1, failed=1, ttl_seconds=1800, items=items)


class BatchSubtitleUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport=dict(width=1440, height=1100))
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.posts = 0
        self.done = False
        self.expired = False
        def route(r):
            if r.request.method == 'POST':
                self.posts += 1
                self.assertTrue(r.request.post_data_json['allow_asr'])
                r.fulfill(json=snapshot())
            elif self.expired:
                r.fulfill(status=404, json=dict(detail='批量任务已过期'))
            elif r.request.url.split('?')[0].endswith('/file'):
                r.fulfill(body=ZIP_BYTES, content_type='application/zip', headers={'Content-Disposition': 'attachment; filename=test.zip'})
            else:
                r.fulfill(json=snapshot(self.done))
        self.page.route('**/api/**', lambda r: r.fulfill(json=dict(ok=True, asr_enabled=True, ai_enabled=True)))
        self.page.route('**/api/batch-transcriptions**', route)
        self.page.goto(BASE + '/batch')
        self.assertEqual(self.page.get_by_label('下载格式').input_value(), 'subtitle')
        self.assertEqual(self.page.get_by_label('下载格式').locator('option').first.get_attribute('value'), 'subtitle')

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def start(self):
        self.page.get_by_role('textbox').fill('\n'.join(URLS))
        self.page.get_by_role('button', name='开始批量提取字幕（3 条）').evaluate('(b) => { b.click(); b.click(); }')
        expect(self.page.get_by_role('heading', name='正在提取字幕')).to_be_visible()
        self.assertEqual(self.posts, 1)

    def test_results_restore_and_exports(self):
        expect(self.page.get_by_role('heading', name='开始提取后，这里会逐条展示字幕结果')).to_be_visible()
        self.start()
        expect(self.page.locator('pre')).to_contain_text('[00:01]')
        expect(self.page.get_by_role('button', name='打包下载字幕')).to_be_disabled()
        self.page.get_by_role('button', name='3. 失败示例', exact=False).click()
        expect(self.page.get_by_role('heading', name='这条视频未能完成提取')).to_be_visible()
        self.page.wait_for_timeout(1400)
        expect(self.page.get_by_role('heading', name='这条视频未能完成提取')).to_be_visible()
        self.done = True
        self.page.reload()
        expect(self.page.get_by_role('heading', name='字幕提取结果')).to_be_visible()
        self.assertEqual(self.posts, 1)
        self.page.get_by_label('显示时间戳').uncheck()
        expect(self.page.locator('pre')).not_to_contain_text('[00:01]')
        with self.page.expect_download() as download:
            self.page.get_by_role('button', name='下载 SRT', exact=True).click()
        self.assertTrue(download.value.suggested_filename.endswith('.srt'))
        with self.page.expect_download() as download:
            self.page.get_by_role('button', name='打包下载字幕').click()
        self.assertTrue(download.value.suggested_filename.endswith('.zip'))
        self.assertEqual(self.posts, 1)

    def test_mobile_layout_and_expired_restore(self):
        self.start()
        self.done = True
        self.page.reload()
        expect(self.page.get_by_role('heading', name='字幕提取结果')).to_be_visible()
        out = Path('C:/Users/yangx/.codex/tmp/free-video-ui')
        out.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(out / 'batch-subtitles-desktop.png'), full_page=True)
        self.page.set_viewport_size(dict(width=390, height=844))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.screenshot(path=str(out / 'batch-subtitles-mobile.png'), full_page=True)
        self.expired = True
        self.page.reload()
        expect(self.page.get_by_role('alert')).to_contain_text('过期')
        expect(self.page.get_by_role('heading', name='开始提取后，这里会逐条展示字幕结果')).to_be_visible()
        self.assertIsNone(self.page.evaluate('localStorage.getItem("fv-batch-subtitles")'))

    def test_zip_failure_is_visible_and_retryable(self):
        self.start()
        self.done = True
        self.page.reload()
        button = self.page.get_by_role('button', name='打包下载字幕')
        expect(button).to_be_enabled()
        self.page.route(f'**/api/batch-transcriptions/{ID}', lambda r: r.fulfill(status=404, json=dict(detail='文件已过期，请重新提取')))
        button.click()
        expect(self.page.get_by_role('status').filter(has_text='文件已过期')).to_be_visible()
        expect(button).to_be_enabled()
        self.page.unroute(f'**/api/batch-transcriptions/{ID}')
        with self.page.expect_download() as event:
            button.click()
        # Native download handoff must use the file URL rather than fetching it into JavaScript.
        self.assertIn(f'/api/batch-transcriptions/{ID}/file', event.value.url)


if __name__ == '__main__':
    unittest.main(verbosity=2)
