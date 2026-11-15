"""Mocked recovery checks; requires Vite on 127.0.0.1:5178. No paid calls."""
import json
import unittest
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:5178'
INFO = dict(url='https://example.com/video', title='Audit video', platform='Test', qualities=[], subtitles=[], duration=60)
USER = dict(id=1, username='tester', nickname='Tester', created_at='2026-11-10T00:00:00Z')


class RecoveryUI(unittest.TestCase):
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
        self.page.route('**/api/**', lambda r: r.fulfill(json=dict(ok=True, ai_enabled=True, asr_enabled=True, plans=[])))
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=USER)))
        self.page.route('**/api/parse', lambda r: r.fulfill(json=INFO))
        self.page.route('**/api/auth/captcha', lambda r: r.fulfill(json=dict(id='ui-test', image='data:image/png;base64,iVBORw0KGgo=', expires_in=300)))

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def prepare_asr(self):
        self.page.route('**/api/learn/summary', lambda r: r.fulfill(body='event: need_asr\ndata: {"asr_enabled":true}\n\n', content_type='text/event-stream'))
        self.page.goto(BASE + '/learn?url=' + INFO['url'])
        self.page.get_by_role('button', name='一键 AI 总结', exact=True).click()
        self.page.get_by_role('button', name='确认语音转文字并总结', exact=True).click()

    def test_no_asr_submit_after_leaving(self):
        pending, posted = [], []
        self.page.route('**/api/transcription-session', lambda r: pending.append(r))
        self.page.route('**/api/transcriptions', lambda r: (posted.append(1), r.abort())[0])
        self.prepare_asr()
        self.page.get_by_role('link', name='定价', exact=True).first.click()
        self.page.wait_for_url(BASE + '/pricing')
        self.assertEqual(len(pending), 1)
        pending[0].fulfill(json=dict(ok=True))
        self.page.wait_for_timeout(200)
        self.assertEqual(posted, [])

    def test_home_auth_check_is_discarded_on_leave(self):
        pending, posted = [], []
        self.page.route('**/api/auth/me', lambda r: pending.append(r))
        self.page.route('**/api/parse', lambda r: (posted.append(1), r.abort())[0])
        self.page.goto(BASE)
        self.page.get_by_role('textbox').first.fill(INFO['url'])
        self.page.get_by_role('tab', name='AI 视频总结', exact=True).click()
        self.page.get_by_role('link', name='定价', exact=True).first.click()
        self.page.wait_for_url(BASE + '/pricing')
        for r in pending:
            r.fulfill(json=dict(user=USER))
        self.page.wait_for_timeout(200)
        self.assertEqual(posted, [])

    def test_clear_chat_discards_late_reply(self):
        pending = []
        self.page.route('**/api/learn/chat', lambda r: pending.append(r))
        self.page.goto(BASE + '/learn?url=' + INFO['url'])
        self.page.get_by_role('button', name='AI 追问', exact=True).click()
        self.page.locator('input[maxlength="1000"]').fill('Audit question')
        self.page.get_by_role('button', name='发送', exact=True).click()
        self.page.get_by_role('button', name='清空对话', exact=True).click()
        for r in pending:
            r.fulfill(body='event: delta\ndata: "late reply"\n\n', content_type='text/event-stream')
        self.page.wait_for_timeout(200)
        expect(self.page.locator('body')).not_to_contain_text('Cannot read properties')
        expect(self.page.locator('body')).not_to_contain_text('late reply')
        self.assertTrue(self.page.get_by_role('button', name='发送', exact=True).is_disabled())

    def test_stream_protocol_and_poll_recovery(self):
        self.page.route('**/api/audit-sse', lambda r: r.fulfill(body='event: delta\r\ndata: "hello"\r\n\r\nevent: done\r\ndata: true', content_type='text/event-stream'))
        reads = []
        def poll(r):
            reads.append(1)
            if len(reads) == 1:
                r.abort()
            else:
                r.fulfill(json=dict(status='done'))
        self.page.route('**/api/jobs/audit', poll)
        self.page.goto(BASE)
        result = self.page.evaluate("""async () => {
          const {streamSSE,pollJob} = await import('/src/api.js');
          const events=[]; await streamSSE('/api/audit-sse',{},(e,d)=>events.push([e,d]));
          const updates=await new Promise(resolve=>{const items=[];const stop=pollJob('audit',j=>{items.push(j);if(j.status==='done'){stop();resolve(items)}},20)});
          return {events,updates};
        }""")
        self.assertEqual(result['events'], [['delta', 'hello'], ['done', True]])
        self.assertEqual(len(reads), 2)
        self.assertFalse(any(j.get('status') == 'error' for j in result['updates']))

    def test_guest_login_does_not_restore_previous_identity_batch(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        self.page.route('**/api/auth/login', lambda r: r.fulfill(json=dict(user=USER)))
        self.page.add_init_script("localStorage.setItem('fv-batch-subtitles','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')")
        restored = []
        self.page.route('**/api/batch-transcriptions/*', lambda r: (restored.append(1), r.fulfill(status=404, json=dict(detail='expired')))[0])
        self.page.goto(BASE + '/batch')
        self.page.evaluate("async () => {const {account}=await import('/src/account.js');await account.ensure();await account.login({username:'tester',password:'password123'})}")
        self.page.wait_for_timeout(200)
        self.assertEqual(restored, [])

    def test_same_account_reload_restores_batch(self):
        self.page.add_init_script("localStorage.setItem('fv-auth-last-user','1');localStorage.setItem('fv-batch-subtitles','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')")
        restored = []
        self.page.route('**/api/batch-transcriptions/*', lambda r: (restored.append(1), r.fulfill(status=404, json=dict(detail='expired')))[0])
        self.page.goto(BASE + '/batch')
        self.page.wait_for_timeout(200)
        self.assertEqual(restored, [1])

    def test_unknown_asr_queries_same_job_without_resubmitting(self):
        posted, reads = [], []
        self.page.route('**/api/transcriptions', lambda r: (posted.append(1), r.fulfill(json=dict(id='audit')))[0])
        self.page.route('**/api/transcriptions/audit', lambda r: (reads.append(1), r.fulfill(json=dict(id='audit', status='error', error_code='SUBMISSION_UNCERTAIN', error='unknown')))[0])
        self.prepare_asr()
        expect(self.page.get_by_text('本次时长暂时冻结', exact=False)).to_be_visible()
        self.page.get_by_role('button', name='查看处理状态', exact=True).click()
        self.page.wait_for_timeout(200)
        self.assertEqual(posted, [1])
        self.assertEqual(len(reads), 2)

    def test_auth_inputs_and_backdrop_clicks(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        self.page.goto(BASE)
        self.page.wait_for_function("document.querySelector('dialog') !== null")
        for width in (1440, 390):
            self.page.set_viewport_size(dict(width=width, height=844))
            for tab in ('login', 'register'):
                self.page.locator('nav').get_by_role('button', name='登录', exact=True, include_hidden=True).first.evaluate('el => el.click()')
                if tab == 'register':
                    self.page.get_by_role('tab', name='注册', exact=True).click()
                dialog = self.page.locator('dialog[open]')
                expect(dialog).to_be_visible()
                username = dialog.get_by_label('邮箱', exact=True)
                username.click()
                username.fill('tester@example.com')
                dialog.get_by_label('密码', exact=True).click()
                dialog.get_by_label('密码', exact=True).fill('password123')
                dialog.get_by_role('button', name='显示密码', exact=True).first.click()
                expect(dialog).to_be_visible()
                # Even a retargeted event within the input's bounds is not a backdrop click.
                box = username.bounding_box()
                dialog.dispatch_event('pointerdown', dict(clientX=box['x'] + 5, clientY=box['y'] + 5))
                dialog.dispatch_event('click', dict(clientX=box['x'] + 5, clientY=box['y'] + 5))
                expect(dialog).to_be_visible()
                # A gesture starting inside and ending on the backdrop must keep the form.
                username.click()
                self.page.mouse.move(box['x'] + 5, box['y'] + 5)
                self.page.mouse.down()
                self.page.mouse.move(2, 2)
                self.page.mouse.up()
                expect(dialog).to_be_visible()
                self.page.mouse.click(2, 2)
                expect(self.page.locator('dialog[open]')).to_have_count(0)

    def test_queued_close_does_not_close_reopened_auth(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        self.page.goto(BASE)
        self.page.wait_for_function("document.querySelector('dialog') !== null")
        self.page.locator('nav').get_by_role('button', name='登录', exact=True).first.click()
        expect(self.page.locator('dialog[open]')).to_be_visible()
        self.page.locator('dialog[open]').evaluate('el => {el.close();el.showModal()}')
        self.page.get_by_label('邮箱', exact=True).click()
        expect(self.page.locator('dialog[open]')).to_be_visible()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('dialog[open]')).to_have_count(0)

    def test_login_error_keeps_form_and_success_closes_it(self):
        self.page.route('**/api/auth/me', lambda r: r.fulfill(json=dict(user=None)))
        self.page.route('**/api/auth/login', lambda r: r.fulfill(status=401, json=dict(detail='Invalid credentials')))
        self.page.goto(BASE)
        self.page.locator('nav').get_by_role('button', name='登录', exact=True).first.click()
        dialog = self.page.locator('dialog[open]')
        dialog.get_by_label('邮箱', exact=True).click()
        dialog.get_by_label('邮箱', exact=True).fill('tester@example.com')
        dialog.get_by_label('密码', exact=True).fill('password123')
        dialog.get_by_role('button', name='登录', exact=True).click()
        expect(dialog.get_by_role('alert')).to_contain_text('Invalid credentials')
        dialog.get_by_label('邮箱', exact=True).click()
        expect(dialog).to_be_visible()
        self.page.route('**/api/auth/login', lambda r: r.fulfill(json=dict(user=USER)))
        dialog.get_by_role('button', name='登录', exact=True).click()
        expect(self.page.locator('dialog[open]')).to_have_count(0)
        expect(self.page.locator('nav').get_by_role('button', name='Tester', exact=True)).to_be_visible()


    def test_switching_to_download_discards_pending_ai_login_check(self):
        pending = []
        self.page.route('**/api/auth/me', lambda r: pending.append(r))
        self.page.goto(BASE)
        self.page.get_by_role('textbox', name='视频链接或分享口令').fill(INFO['url'])
        self.page.get_by_role('tab', name='AI 视频总结', exact=True).click()
        download = self.page.get_by_role('tab', name='素材与文案下载', exact=True)
        download.click()
        for route in pending:
            route.fulfill(json=dict(user=USER))
        self.page.wait_for_timeout(250)
        expect(download).to_have_attribute('aria-selected', 'true')


if __name__ == '__main__':
    unittest.main(verbosity=2)
