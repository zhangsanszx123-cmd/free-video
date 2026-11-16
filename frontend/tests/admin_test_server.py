"""Isolated admin browser backend on :8015; never uses the business database.

Run from repo root: backend/.venv/Scripts/python -P frontend/tests/admin_test_server.py
All fixture passwords are test-only. SMTP, payment and paid providers are disabled.
Do not run pytest against this server's freevideo_admin_ui_test database.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DATABASE = 'freevideo_admin_ui_test'
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.update(
    MYSQL_DATABASE=DATABASE, MYSQL_TEST_DATABASE=DATABASE,
    AUTH_EMAIL_VERIFICATION_REQUIRED='false', AUTH_REGISTER_RATE_LIMIT='500', AUTH_LOGIN_RATE_LIMIT='500',
    DEEPSEEK_API_KEY='', DASHSCOPE_API_KEY='', ZPAY_PID='', ZPAY_KEY='', ZPAY_MOCK='false',
    PAYMENT_RECONCILE_SECONDS='0', PUBLIC_BASE_URL='http://127.0.0.1:8015', SESSION_SECURE='false',
    SMTP_HOST='', SMTP_USER='', SMTP_PASSWORD='', SMTP_FROM='',
    DOWNLOAD_DIR=str(ROOT / '.runtime/admin-ui/downloads'), ASR_DIR=str(ROOT / '.runtime/admin-ui/transcriptions'),
)

import pymysql
from app import account_auth, account_store, admin_store, config, membership


def seed_fixtures():
    assert config.MYSQL_DATABASE == DATABASE and DATABASE.endswith('_admin_ui_test')
    assert not config.ZPAY_PID and not config.ZPAY_KEY and not config.DASHSCOPE_API_KEY and not config.DEEPSEEK_API_KEY
    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                           password=config.MYSQL_PASSWORD, charset='utf8mb4')
    with conn, conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE IF NOT EXISTS `{DATABASE}` DEFAULT CHARACTER SET utf8mb4')
    account_store.init_schema()
    admin_store.init_schema()
    with account_store._cursor() as cur:
        for table in ('admin_audit_logs', 'admin_sessions', 'admin_users', 'payment_events',
                      'payment_orders', 'guest_links', 'sessions', 'users', 'membership_plans'):
            cur.execute(f'DELETE FROM {table}')
    membership.seed()
    password_hash = account_auth.hash_password('Admin UI password 2026')
    admin_store.bootstrap('admin_fixture', '测试超级管理员', password_hash)
    now = account_store.utcnow()
    with account_store._cursor() as cur:
        cur.execute('INSERT INTO admin_users '
                    '(username,username_key,nickname,password_hash,role,status,created_at,updated_at,password_changed_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    ('staff_fixture', 'staff_fixture', '测试普通管理员', password_hash, 'admin', 'active', now, now, now))
    site_hash = account_auth.hash_password('Site UI password 2026')
    for index in range(23):
        account_store.create_user(f'u_fixture_{index}', f'u_fixture_{index}', f'测试用户 {index:02d}', site_hash,
                                  None, email=f'admin-member-{index:02d}@example.com', verified=index != 22)
    membership.grant('admin-member-00@example.com', 'monthly')


if __name__ == '__main__':
    seed_fixtures()
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8015, log_level='warning')
