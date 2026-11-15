import time

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture(autouse=True)
def tmp_downloads(tmp_path, monkeypatch, request):
    monkeypatch.setattr(config, 'AUTH_EMAIL_VERIFICATION_REQUIRED', False)
    for name in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM'):
        monkeypatch.setattr(config, name, '')
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(config, "ASR_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", None)
    # Never call the real ZPAY from tests; payment tests enable the in-process mock explicitly.
    for name, value in (("ZPAY_PID", None), ("ZPAY_KEY", None), ("ZPAY_MOCK", False),
                        ("PAYMENT_RECONCILE_SECONDS", 0), ("PUBLIC_BASE_URL", "http://testserver")):
        monkeypatch.setattr(config, name, value)
    from app.transcriptions import TranscriptionManager
    from app import transcription_auth
    transcription_auth._rates.clear()
    isolated = TranscriptionManager()
    monkeypatch.setattr(main, "transcription_manager", isolated)
    from app.batch_transcriptions import BatchTranscriptionManager
    batches = BatchTranscriptionManager(lambda: isolated)
    monkeypatch.setattr(main, 'batch_transcription_manager', batches)
    config.DOWNLOAD_DIR.mkdir()
    from app import account_auth, account_store, membership
    from fastapi import Request
    account_auth.reset_limits()
    # Never touch the real accounts database from tests; test_accounts.py points it at MYSQL_TEST_DATABASE.
    monkeypatch.setattr(config, "MYSQL_DATABASE", config.MYSQL_TEST_DATABASE or "freevideo_test_unconfigured")
    monkeypatch.setattr(account_store, "init_schema", lambda: None)
    # Feature tests run as a logged-in user; account tests remove this override to exercise real auth.
    def fake_current(req: Request):
        uid = req.cookies.get('fv-test-user')
        return {'id': int(uid), 'username': 'tester', 'nickname': 'tester', 'session_id': '0' * 32} if uid else None
    def fake_required(req: Request):
        user = fake_current(req) or {'id': 2, 'username': 'outsider', 'session_id': '1' * 32}
        req.state.account_user = user
        return user
    main.app.dependency_overrides[account_auth.require_user] = fake_required
    main.app.dependency_overrides[account_auth.current_user] = fake_current
    # Legacy ASR tests exercise provider/cost behaviour with no database. Dedicated membership/account
    # tests retain the real repository and a configured MySQL test database.
    if request.module.__name__.split('.')[-1] not in ('test_membership', 'test_accounts', 'test_payments', 'test_limits', 'test_guest'):
        for name in ('seed', 'create_record', 'persist', 'complete', 'reserve', 'alias_key', 'save_alias', 'hide', 'cleanup', 'recover'):
            monkeypatch.setattr(membership, name, lambda *a, **k: None)
        monkeypatch.setattr(membership, 'record', lambda *a, **k: None)
        monkeypatch.setattr(membership, 'limits', lambda *a, **k: None)
        from app import usage
        for name in ('ai_begin', 'ai_release', 'chat_begin', 'chat_release'):
            monkeypatch.setattr(usage, name, lambda *a, **k: None)
    yield config.DOWNLOAD_DIR
    main.app.dependency_overrides.pop(account_auth.require_user, None)
    main.app.dependency_overrides.pop(account_auth.current_user, None)
    batches.stopping.set()
    batches.pool.shutdown(wait=True, cancel_futures=True)
    isolated.stop()
    isolated.pool.shutdown(wait=True, cancel_futures=True)


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        c.cookies.set('fv-test-user', '1')
        yield c


def wait_job(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.05)
    raise AssertionError("job timeout")
