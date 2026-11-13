"""ZPAY purchase flow in a real browser against a REAL backend using the local mock cashier (no money).

1. cd frontend && npm run build
2. Start a test backend (PowerShell):
   cd backend; $env:MYSQL_DATABASE='freevideo_test'; $env:ZPAY_MOCK='true'; $env:ZPAY_PID=''; $env:ZPAY_KEY='';
   $env:PUBLIC_BASE_URL='http://127.0.0.1:8011'; $env:DEEPSEEK_API_KEY=''; $env:DASHSCOPE_API_KEY='';
   $env:AUTH_REGISTER_RATE_LIMIT='100'; $env:AUTH_LOGIN_RATE_LIMIT='100'
   .venv/Scripts/python -m uvicorn app.main:app --port 8011
3. python -P frontend/tests/payment_ui.py      (PAYMENT_UI_BASE overrides http://127.0.0.1:8011)
Screenshots go to .runtime/payment-ui/. Each test registers a fresh random user and deletes it afterwards.
"""
import os
import secrets
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.getenv('PAYMENT_UI_BASE', 'http://127.0.0.1:8011')
SHOTS = Path(__file__).resolve().parents[2] / '.runtime' / 'payment-ui'
PASSWORD = 'Pay e2e 2026'


class PaymentUI(unittest.TestCase):
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
        self.username = 'pay_ui_' + secrets.token_hex(4)
        res = self.page.request.post(BASE + '/api/auth/register', data=dict(username=self.username, password=PASSWORD))
        self.assertTrue(res.ok, res.text())

    def tearDown(self):
        self.page.request.delete(BASE + '/api/account', data=dict(password=PASSWORD, confirm_username=self.username))
        self.context.close()
        self.assertEqual(self.errors, [])

    def orders(self):
        return self.page.request.get(BASE + '/api/pay/orders').json()['orders']

    def checkout(self, button, action='模拟支付成功'):
        p = self.page
        p.get_by_role('button', name=button, exact=True).click()
        dialog = p.locator('dialog[aria-labelledby="pay-title"]')
        expect(dialog).to_be_visible()
        dialog.get_by_role('button', name='前往支付宝付款', exact=False).click()
        expect(p.get_by_text('模拟支付 · 不会扣钱')).to_be_visible()
        p.get_by_role('button', name=action, exact=True).click()
        p.wait_for_url('**/pay/result?**')
        expect(p.get_by_role('heading', name='支付成功，会员已开通')).to_be_visible(timeout=15000)

    def test_guest_login_then_pay_and_renew_upgrade(self):
        p = self.page
        p.request.post(BASE + '/api/auth/logout', data={})
        p.goto(BASE + '/pricing')
        expect(p.locator('article').nth(1)).to_contain_text('支付宝付款')
        p.get_by_role('button', name='开通月卡', exact=True).click()
        auth = p.locator('dialog[aria-labelledby="auth-title"]')
        expect(auth).to_contain_text('登录后即可开通会员')
        auth.get_by_label('用户名').fill(self.username)
        auth.get_by_label('密码', exact=True).fill(PASSWORD)
        auth.get_by_role('button', name='登录', exact=True).click()
        dialog = p.locator('dialog[aria-labelledby="pay-title"]')
        expect(dialog).to_contain_text('¥19.90')
        expect(dialog).to_contain_text('立即生效')
        dialog.screenshot(path=SHOTS / 'pay-modal.png')
        dialog.get_by_role('button', name='前往支付宝付款', exact=False).click()
        expect(p.get_by_text('模拟支付 · 不会扣钱')).to_be_visible()
        expect(p.get_by_text('¥19.90')).to_be_visible()
        p.screenshot(path=SHOTS / 'mock-cashier.png')
        p.get_by_role('button', name='模拟支付成功', exact=True).click()
        p.wait_for_url('**/pay/result?**')
        expect(p.get_by_role('heading', name='支付成功，会员已开通')).to_be_visible(timeout=15000)
        p.screenshot(path=SHOTS / 'result-paid.png')
        p.get_by_role('link', name='查看会员与订单').click()
        expect(p.get_by_role('region', name='语音识别额度')).to_contain_text('月卡会员')
        expect(p.locator('#orders-title').locator('..').locator('..')).to_contain_text('已支付')
        p.goto(BASE + '/pricing')
        expect(p.get_by_role('button', name='续费月卡', exact=True)).to_be_enabled()
        self.checkout('升级年卡')
        p.goto(BASE + '/pricing')
        monthly = p.get_by_role('button', name='开通月卡', exact=True)
        expect(monthly).to_be_disabled()
        expect(p.locator('article').nth(1)).to_contain_text('年卡有效期内无需购买月卡')
        expect(p.get_by_role('button', name='续费年卡', exact=True)).to_be_enabled()
        self.assertEqual([o['fulfilment'] for o in self.orders()], ['upgrade', 'new'])

    def test_no_notify_is_confirmed_by_query_and_double_click_creates_one_order(self):
        p = self.page
        p.goto(BASE + '/pricing')
        p.get_by_role('button', name='开通年卡', exact=True).click()
        dialog = p.locator('dialog[aria-labelledby="pay-title"]')
        dialog.get_by_role('button', name='前往支付宝付款', exact=False).dblclick()
        p.get_by_role('button', name='支付成功但不发异步通知（测试主动查单）', exact=True).click()
        p.wait_for_url('**/pay/result?**')
        expect(p.get_by_role('heading', name='支付成功，会员已开通')).to_be_visible(timeout=15000)
        self.assertEqual(len(self.orders()), 1)

    def test_cancel_and_responsive(self):
        p = self.page
        for width in (360, 390, 768):
            p.set_viewport_size(dict(width=width, height=900))
            p.goto(BASE + '/pricing')
            p.get_by_role('button', name='开通月卡', exact=True).click()
            expect(p.locator('dialog[aria-labelledby="pay-title"]')).to_be_visible()
            self.assertTrue(p.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            p.screenshot(path=SHOTS / f'pay-modal-{width}.png')
            p.keyboard.press('Escape')
            expect(p.locator('dialog[aria-labelledby="pay-title"]')).to_be_hidden()
        p.get_by_role('button', name='开通月卡', exact=True).click()
        p.locator('dialog[aria-labelledby="pay-title"]').get_by_role('button', name='前往支付宝付款', exact=False).click()
        p.get_by_role('button', name='取消支付', exact=True).click()
        p.wait_for_url('**/pricing')
        self.assertEqual([o['status'] for o in self.orders()], ['pending'])
        p.goto(BASE + '/pay/result?out_trade_no=' + self.orders()[0]['out_trade_no'])
        expect(p.get_by_role('heading', name='正在确认支付结果…')).to_be_visible()
        p.goto(BASE + '/pay/result?out_trade_no=12345')
        expect(p.get_by_role('heading', name='查询订单失败')).to_be_visible()
        self.assertTrue(p.evaluate('document.documentElement.scrollWidth <= innerWidth'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
