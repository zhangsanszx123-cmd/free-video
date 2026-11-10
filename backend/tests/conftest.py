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
    yield config.DOWNLOAD_DIR
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
