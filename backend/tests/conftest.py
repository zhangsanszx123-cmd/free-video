import time

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture(autouse=True)
def tmp_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(config, "ASR_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", None)
    from app.transcriptions import TranscriptionManager
    from app import transcription_auth
    transcription_auth._rates.clear()
    isolated = TranscriptionManager()
    monkeypatch.setattr(main, "transcription_manager", isolated)
    from app.batch_transcriptions import BatchTranscriptionManager
    batches = BatchTranscriptionManager(lambda: isolated)
    monkeypatch.setattr(main, 'batch_transcription_manager', batches)
    config.DOWNLOAD_DIR.mkdir()
    from app import account_auth, account_store
    account_auth.reset_limits()
    # Never touch the real accounts database from tests; test_accounts.py points it at MYSQL_TEST_DATABASE.
    monkeypatch.setattr(config, "MYSQL_DATABASE", config.MYSQL_TEST_DATABASE or "freevideo_test_unconfigured")
    monkeypatch.setattr(account_store, "init_schema", lambda: None)
    # Feature tests run as a logged-in user; account tests remove this override to exercise real auth.
    main.app.dependency_overrides[account_auth.require_user] = lambda: {
        "id": 1, "username": "tester", "nickname": "tester", "session_id": "0" * 32}
    yield config.DOWNLOAD_DIR
    main.app.dependency_overrides.pop(account_auth.require_user, None)
    batches.stopping.set()
    batches.pool.shutdown(wait=True, cancel_futures=True)
    isolated.stop()
    isolated.pool.shutdown(wait=True, cancel_futures=True)


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def wait_job(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.05)
    raise AssertionError("job timeout")
