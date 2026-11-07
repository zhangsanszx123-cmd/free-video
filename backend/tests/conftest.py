import time

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture(autouse=True)
def tmp_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path / "downloads")
    config.DOWNLOAD_DIR.mkdir()
    return config.DOWNLOAD_DIR


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
