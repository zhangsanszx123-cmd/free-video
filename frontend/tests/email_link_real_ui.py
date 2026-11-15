"""Real backend verification flow against frontend/tests/email_link_test_server.py (:8014).
Only SMTP is replaced by a private local outbox. Never run against the business DB.
"""
import json
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_helpers import fill_captcha
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[2]
base = 'http://127.0.0.1:8014'
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        context = browser.new_context(viewport=dict(width=width, height=1000))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        email = 'verify_' + secrets.token_hex(4) + '@example.com'
        page.goto(base+'/register')
        page.get_by_label('邮箱', exact=True).fill(email)
        page.get_by_label('密码', exact=True).fill('Real test password 2026')
        fill_captcha(page)
        page.get_by_role('button', name='注册账号', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='验证邮件已发送')).to_be_visible()
        assert page.request.get(base+'/api/auth/me').json()['user'] is None
        link = json.loads((root/'.runtime/email-link-test-outbox.json').read_text(encoding='utf-8'))[email]
        verification = context.new_page()
        verification.goto(link)
        expect(verification.get_by_role('button', name='确认验证并登录')).to_be_visible()
        assert verification.request.get(base+'/api/auth/me').json()['user'] is None
        verification.get_by_role('button', name='确认验证并登录').click()
        expect(verification.get_by_role('status').filter(has_text='邮箱验证成功')).to_be_visible()
        assert verification.request.get(base+'/api/auth/me').json()['user']['email'] == email
        page.wait_for_url(base+'/')  # cross-tab activation resumes guest-only registration page
        verification.goto(link)
        verification.get_by_role('button', name='确认验证并登录').click()
        expect(verification.get_by_role('alert')).to_contain_text('无效或已过期')
        verification.goto(base+'/forgot-password')
        verification.get_by_label('注册邮箱').fill(email)
        verification.get_by_role('button',name='发送重置邮件',exact=True).click()
        expect(verification.get_by_role('status').filter(has_text='如果该邮箱已注册')).to_be_visible()
        reset_link=json.loads((root/'.runtime/email-link-test-outbox.json').read_text(encoding='utf-8'))[email]
        assert '/reset-password#' in reset_link
        verification.goto(reset_link)
        verification.get_by_label('新密码').fill('Recovered password 2026')
        verification.get_by_role('button',name='重置密码',exact=True).click()
        expect(verification.get_by_role('status').filter(has_text='密码已重置')).to_be_visible()
        assert verification.request.get(base+'/api/auth/me').json()['user'] is None
        assert verification.request.post(base+'/api/auth/login',data=dict(email=email,password='Real test password 2026')).status==401
        assert verification.request.post(base+'/api/auth/login',data=dict(email=email,password='Recovered password 2026')).status==200
        assert not errors, errors
        context.close()
        print(f'PASS real email activation and password recovery at {width}px')
    browser.close()
