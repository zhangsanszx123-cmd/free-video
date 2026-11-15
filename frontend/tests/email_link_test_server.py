"""Isolated :8014 backend for email_link_real_ui.py. SMTP is always replaced.

Run from repo root with backend/.venv/Scripts/python -P frontend/tests/email_link_test_server.py.
Uses freevideo_test only; no real email, AI, ASR or payment requests.
"""
import os
import sys
import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.update(MYSQL_DATABASE='freevideo_test', DEEPSEEK_API_KEY='', DASHSCOPE_API_KEY='',
                  AUTH_REGISTER_RATE_LIMIT='100', AUTH_LOGIN_RATE_LIMIT='100',
                  PAYMENT_RECONCILE_SECONDS='0', ZPAY_PID='', ZPAY_KEY='', ZPAY_MOCK='false',
                  AUTH_EMAIL_VERIFICATION_REQUIRED='true', SMTP_HOST='test', SMTP_USER='test',
                  SMTP_PASSWORD='test', SMTP_FROM='test@example.com', PUBLIC_BASE_URL='http://127.0.0.1:8014')
from app import email_verification

out = ROOT / '.runtime/email-link-test-outbox.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text('{}', encoding='utf-8')
lock = threading.Lock()


def fake_send(recipient, link, **kwargs):
    with lock:
        content = json.loads(out.read_text(encoding='utf-8'))
        content[recipient] = link
        out.write_text(json.dumps(content), encoding='utf-8')


email_verification.send_email = fake_send
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8014, log_level='warning')
