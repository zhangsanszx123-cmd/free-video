import json
from types import SimpleNamespace
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app import asr, config, downloader, main, transcription_auth, transcriptions
from app.asr import Recognition
from app.asr_ledger import Ledger
from app.errors import EmptySubtitles, NoSubtitles, TranscriptionError, VideoError
from app.subtitles import Cue, parse_srt

SAMPLE = [Cue("00:00:00,120", "00:00:02,300", "你好，Hello world。")]


def wait(client, job_id):
    for _ in range(200):
        response = client.get(f"/api/transcriptions/{job_id}")
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] in ("done", "error"):
            return value
        time.sleep(0.01)
    raise AssertionError("transcription timeout")


@pytest.fixture
def cloud(monkeypatch):
    for key, value in {"DASHSCOPE_API_KEY": "test-key", "OSS_BUCKET": "test-bucket",
                       "OSS_ACCESS_KEY_ID": "id", "OSS_ACCESS_KEY_SECRET": "secret",
                       "ASR_POLL_SECONDS": 0.001, "ASR_PROVIDER": "paraformer",
                       "ASR_MODEL": "paraformer-v2", "ASR_PRICE_PER_SECOND": "0.00008"}.items():
        monkeypatch.setattr(config, key, value)
    calls = {"submit": 0, "upload": 0, "delete": 0, "query": 0}

    def no_sub(*args, **kwargs):
        raise NoSubtitles("无字幕")
    monkeypatch.setattr(transcriptions, "read_subtitles", no_sub)
    monkeypatch.setattr(downloader, "parse", lambda url: {"title": "中文/视频", "url": "https://example.com/video/1", "duration": 3})

    def audio(url, directory, report):
        path = directory / "input.mp3"
        path.write_bytes(b"audio")
        return path, 3.0
    monkeypatch.setattr(transcriptions, "acquire_audio", audio)

    class Storage:
        def upload(self, key, path):
            calls["upload"] += 1
            return "https://private.example/audio?secret=not-public"
        def delete(self, key):
            calls["delete"] += 1
    monkeypatch.setattr(transcriptions, "TemporaryStorage", Storage)

    class Provider:
        def submit(self, url):
            calls["submit"] += 1
            return "internal-cloud-task"
        def query(self, task_id):
            calls["query"] += 1
            return Recognition("SUCCEEDED", SAMPLE, 2)
    monkeypatch.setattr(asr, "get_provider", Provider)
    return calls


@pytest.mark.parametrize("auto,source", [(False, "platform_subtitle"), (True, "automatic_subtitle")])
def test_subtitles_never_call_asr(client, monkeypatch, auto, source):
    def subtitles(url, directory, lang=None):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "test.srt"
        path.write_text("1\n00:00:00,120 --> 00:00:02,300\n平台内容\n", encoding="utf-8")
        info = {"title": "平台", "automatic_captions" if auto else "subtitles": {"zh": [{}]}}
        return path, info
    monkeypatch.setattr(downloader, "download_subtitle", subtitles)
    monkeypatch.setattr(asr, "get_provider", lambda: pytest.fail("must not call ASR"))
    response = client.post("/api/transcript", json={"url": "https://example.com/1"})
    assert response.json()["source"] == source
    job = client.post("/api/transcriptions", json={"url": "https://example.com/1", "allow_asr": True}).json()
    value = wait(client, job["id"])
    assert value["status"] == "done" and value["result"]["source"] == source
    assert parse_srt(value["result"]["srt"])[0].text == "平台内容"


def test_success_dedup_exports_and_isolation(client, cloud):
    request = {"url": "https://example.com/video/1", "allow_asr": True}
    job = client.post("/api/transcriptions", json=request).json()
    value = wait(client, job["id"])
    assert value["status"] == "done", value
    assert value["result"]["source"] == "asr"
    assert cloud["submit"] == 1 and cloud["delete"] == 1
    duplicate = client.post("/api/transcriptions", json=request).json()
    assert duplicate["id"] == job["id"] and cloud["submit"] == 1
    for ext in ("txt", "srt"):
        response = client.get(f"/api/transcriptions/{job['id']}/file?format={ext}")
        assert response.status_code == 200 and "你好" in response.text
        assert "no-store" in response.headers["cache-control"]
    assert client.get(f"/api/jobs/{job['id']}/file").status_code == 404
    with TestClient(main.app) as outsider:
        assert outsider.get(f"/api/transcriptions/{job['id']}").status_code == 404
        assert outsider.get(f"/api/transcriptions/{job['id']}/file").status_code == 404
    assert "private.example" not in json.dumps(value) and "internal-cloud-task" not in json.dumps(value)
    entry = main.transcription_manager.ledger.entries()[job["id"]]
    assert entry["state"] == "settled" and entry["object_key"] is None
    assert not (main.transcription_manager.jobs[job["id"]].directory / "input.mp3").exists()


def test_no_asr_without_explicit_trigger(client, cloud):
    job = client.post("/api/transcriptions", json={"url": "https://example.com/1"}).json()
    value = wait(client, job["id"])
    assert value["error_code"] == "ASR_REQUIRED" and cloud["submit"] == 0


@pytest.mark.parametrize("exception,code", [(NoSubtitles("没有字幕"), "NO_SUBTITLES"), (EmptySubtitles("空字幕"), "EMPTY_SUBTITLES")])
def test_structured_subtitle_errors(client, monkeypatch, exception, code):
    def fail(*args):
        raise exception
    monkeypatch.setattr(transcriptions, "read_subtitles", fail)
    # main imports the function explicitly.
    monkeypatch.setattr(main, "read_subtitles", fail)
    value = client.post("/api/transcript", json={"url": "https://example.com/1"})
    assert value.json()["code"] == code


def test_network_subtitle_failure_does_not_fallback(client, cloud, monkeypatch):
    def fail(*args):
        raise VideoError("字幕下载网络失败")
    monkeypatch.setattr(transcriptions, "read_subtitles", fail)
    job = client.post("/api/transcriptions", json={"url": "https://example.com/1", "allow_asr": True}).json()
    assert wait(client, job["id"])["error_code"] == "VIDEO_FAILED"
    assert cloud["submit"] == cloud["upload"] == 0


@pytest.mark.parametrize("kind", ["disabled", "budget", "too_long", "no_speech", "cloud_failure", "upload", "unknown"])
def test_cloud_error_boundaries(client, cloud, monkeypatch, kind):
    expected = {"disabled": "ASR_DISABLED", "budget": "BUDGET_EXCEEDED", "too_long": "AUDIO_TOO_LONG",
                "no_speech": "NO_SPEECH", "cloud_failure": "RECOGNITION_FAILED", "upload": "UPLOAD_FAILED",
                "unknown": "SUBMISSION_UNCERTAIN"}[kind]
    if kind == "disabled":
        monkeypatch.setattr(config, "DASHSCOPE_API_KEY", None)
    elif kind == "budget":
        monkeypatch.setattr(config, "ASR_DAILY_BUDGET", "0")
    elif kind == "too_long":
        monkeypatch.setattr(config, "ASR_MAX_DURATION", 1)
    elif kind == "upload":
        class Storage:
            def upload(self, *args):
                raise TranscriptionError("UPLOAD_FAILED", "上传失败", True)
            def delete(self, key):
                cloud["delete"] += 1
        monkeypatch.setattr(transcriptions, "TemporaryStorage", Storage)
    else:
        class Provider:
            def submit(self, url):
                cloud["submit"] += 1
                if kind == "unknown":
                    raise TranscriptionError("CLOUD_NETWORK", "网络中断", True)
                return "cloud-id"
            def query(self, task_id):
                return Recognition("FAILED" if kind == "cloud_failure" else "SUCCEEDED", [], 0)
        monkeypatch.setattr(asr, "get_provider", Provider)
    req = {"url": "https://example.com/video/1", "allow_asr": True}
    job = client.post("/api/transcriptions", json=req).json()
    result = wait(client, job["id"])
    assert result["status"] == "error" and result["error_code"] == expected, result
    entries = main.transcription_manager.ledger.entries()
    if kind == "unknown":
        assert entries[job["id"]]["state"] == "unknown"
        assert cloud["delete"] == 0 and not result["retryable"]
        assert client.post("/api/transcriptions", json=req).json()["id"] == job["id"]
    elif kind == "upload":
        assert entries[job["id"]]["state"] == "released" and cloud["delete"] == 1
    elif kind in ("no_speech", "cloud_failure"):
        assert entries[job["id"]]["state"] == "settled" and cloud["delete"] == 1
    else:
        assert cloud["submit"] == 0


def test_rate_origin_and_tampered_cookie(client, monkeypatch):
    monkeypatch.setattr(config, "ASR_RATE_LIMIT", 1)
    transcription_auth._rates.clear()
    assert client.post("/api/transcriptions", headers={"Origin": "https://evil.example"}, json={"url": "https://example.com/1"}).status_code == 403
    response = client.get("/api/transcription-session")
    signed = client.cookies.get(transcription_auth.COOKIE)
    assert signed and "httponly" in response.headers.get("set-cookie", "").lower()
    client.post("/api/transcriptions", json={"url": "no url"})
    assert client.post("/api/transcriptions", json={"url": "https://example.com/1"}).status_code == 429
    client.cookies.clear()
    client.cookies.set(transcription_auth.COOKIE, signed[:-3] + "bad")
    assert client.get("/api/transcriptions/unknown").status_code == 404
    transcription_auth._rates.clear()


def test_capacity_and_atomic_dedup(cloud, monkeypatch):
    manager = main.transcription_manager
    manager.recovery_ready = True
    monkeypatch.setattr(config, "ASR_WORKERS", 1)
    monkeypatch.setattr(config, "ASR_MAX_QUEUE", 0)
    gate = threading.Event()
    monkeypatch.setattr(manager, "_run", lambda job: gate.wait(5))
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(lambda _: manager.submit("owner", "https://example.com/1", allow_asr=True), range(8)))
        assert len({j.id for j in jobs}) == 1
        with pytest.raises(TranscriptionError, match="任务已满"):
            manager.submit("owner", "https://example.com/2", allow_asr=True)
    finally:
        gate.set()


def test_ledger_persistence_concurrency_and_corruption(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ASR_PRICE_PER_SECOND", "0.00008")
    monkeypatch.setattr(config, "ASR_DAILY_BUDGET", "0.0008")
    ledger = Ledger(tmp_path / "usage.json")
    def reserve(i):
        try:
            ledger.reserve(str(i), 10, f"freevideo-asr/{i}.mp3")
            return True
        except TranscriptionError:
            return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(reserve, range(10))) == 1
    reloaded = Ledger(ledger.path)
    assert len(reloaded.entries()) == 1
    ledger.path.write_text('{"version":1,"entries":{"x":{}}}', encoding="utf-8")
    with pytest.raises(TranscriptionError, match="账本异常"):
        reloaded.reserve("new", 1, "freevideo-asr/new.mp3")


def test_restart_reconcile_and_cleanup(cloud):
    manager = main.transcription_manager
    manager.ledger.reserve("old", 10, "freevideo-asr/old.mp3")
    manager.ledger.update("old", state="submitted", task_id="old-id")
    restarted = transcriptions.TranscriptionManager()
    try:
        restarted.reconcile()
        entry = restarted.ledger.entries()["old"]
        assert entry["state"] == "settled" and entry["object_key"] is None
        assert cloud["submit"] == 0 and cloud["delete"] == 1
    finally:
        restarted.pool.shutdown()


def test_ttl_uses_completion_and_keeps_active(cloud):
    manager = main.transcription_manager
    job = transcriptions.Transcription("test-id", "owner", "key", "https://example.com", None, True)
    manager.jobs[job.id] = job
    job.directory.mkdir(parents=True)
    job.created_at = time.time() - 100000
    manager.cleanup()
    assert job.directory.exists()
    job.status, job.finished_at = "done", time.time()
    manager.cleanup()
    assert job.directory.exists()
    manager.cleanup(now=time.time() + config.FILE_TTL_SECONDS + 1)
    assert job.id not in manager.jobs and not job.directory.exists()


@pytest.mark.parametrize("start,end", [(-1, 10), (100, 100), (200, 100), (None, 100), (True, 100)])
def test_invalid_asr_timestamps(start, end):
    with pytest.raises(TranscriptionError):
        asr.normalize_sentences({"transcripts": [{"sentences": [{"text": "你好", "begin_time": start, "end_time": end}]}]})


def test_paraformer_http_contract(monkeypatch):
    monkeypatch.setattr(config, "ASR_MODEL", "paraformer-v2")
    requests = []
    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        payload = {"output": {"task_id": "task-id", "task_status": "PENDING"}}
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(asr.httpx, "request", request)
    provider = asr.Paraformer()
    assert provider.submit("https://private.test/audio") == "task-id"
    assert provider.query("task-id").status == "PENDING"
    method, url, args = requests[0]
    assert method == "POST" and url.endswith("/services/audio/asr/transcription")
    assert args["headers"]["X-DashScope-Async"] == "enable"
    assert args["json"]["model"] == "paraformer-v2"
    assert args["json"]["parameters"]["disfluency_removal_enabled"] is False
    assert requests[1][0] == "GET" and requests[1][1].endswith("/tasks/task-id")


@pytest.mark.parametrize("payload,code", [
    ({"streams": [], "format": {"duration": "3"}}, "NO_AUDIO"),
    ({"streams": [{"codec_type": "audio"}], "format": {"duration": str(config.ASR_MAX_DURATION + 1)}}, "AUDIO_TOO_LONG"),
    ({"streams": [{"codec_type": "audio"}], "format": {"duration": "nan"}}, "INVALID_AUDIO"),
])
def test_actual_probe_validation(monkeypatch, tmp_path, payload, code):
    monkeypatch.setattr(transcriptions.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode()))
    with pytest.raises(TranscriptionError) as exc:
        transcriptions.probe_audio(tmp_path / "test.mp3")
    assert exc.value.code == code


def test_result_schema_and_subtask_failure(monkeypatch):
    def response(method, url, **kwargs):
        return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED", "results": [{"subtask_status": "FAILED"}]}, "usage": {"duration": 0}})
    monkeypatch.setattr(asr.httpx, "request", response)
    value = asr.Paraformer().query("id")
    assert value.status == "FAILED" and value.duration == 0
    cues = asr.normalize_sentences({"transcripts": [{"channel_id": 0, "sentences": [
        {"begin_time": 100, "end_time": 1200, "text": "你好"},
        {"begin_time": 1200, "end_time": 2800, "text": "Hello world"}]}]})
    assert cues[0].start == "00:00:00,100" and cues[1].end == "00:00:02,800"


def test_delete_failure_retried_after_restart(cloud, monkeypatch):
    manager = main.transcription_manager
    manager.ledger.reserve("cleanup", 1, "freevideo-asr/cleanup.mp3")
    manager.ledger.update("cleanup", state="released")
    class Broken:
        def delete(self, key):
            raise RuntimeError("temporary failure")
    manager._delete_object("cleanup", "freevideo-asr/cleanup.mp3", Broken())
    assert manager.ledger.entries()["cleanup"]["object_key"] is not None
    manager.reconcile()
    assert manager.ledger.entries()["cleanup"]["object_key"] is None


def test_unknown_reservation_survives_new_day_and_task_ttl(cloud, monkeypatch):
    ledger = main.transcription_manager.ledger
    ledger.reserve("unknown", 100, "freevideo-asr/unknown.mp3", "fingerprint")
    ledger.update("unknown", state="unknown", date="2000-01-01")
    with pytest.raises(TranscriptionError) as exc:
        ledger.reserve("new", 100, "freevideo-asr/new.mp3", "fingerprint")
    assert exc.value.code == "SUBMISSION_UNCERTAIN"
    monkeypatch.setattr(config, "ASR_DAILY_BUDGET", "0.008")
    with pytest.raises(TranscriptionError) as exc:
        ledger.reserve("other", 1, "freevideo-asr/other.mp3", "other")
    assert exc.value.code == "BUDGET_EXCEEDED"


@pytest.mark.parametrize("second_request", [
    {"url": "https://short.example/share", "allow_asr": True},
    {"url": "https://example.com/video/1", "lang": "en", "allow_asr": True},
])
def test_alias_url_reuses_owned_task(client, cloud, second_request):
    first = client.post("/api/transcriptions", json={"url": "https://example.com/video/1", "allow_asr": True}).json()
    assert wait(client, first["id"])["status"] == "done"
    alias = client.post("/api/transcriptions", json=second_request).json()
    resolved = wait(client, alias["id"])
    assert resolved["id"] == first["id"] and cloud["submit"] == 1
    assert client.get(f"/api/transcriptions/{alias['id']}/file?format=srt").status_code == 200


def test_poll_network_failure_never_resubmits(client, cloud, monkeypatch):
    class Provider:
        def submit(self, url):
            cloud["submit"] += 1
            return "id"
        def query(self, task_id):
            cloud["query"] += 1
            if cloud["query"] == 1:
                raise TranscriptionError("CLOUD_NETWORK", "查询网络中断", True)
            return Recognition("SUCCEEDED", SAMPLE, 2)
    monkeypatch.setattr(asr, "get_provider", Provider)
    job = client.post("/api/transcriptions", json={"url": "https://example.com/video/1", "allow_asr": True}).json()
    assert wait(client, job["id"])["status"] == "done"
    assert cloud["submit"] == 1 and cloud["query"] == 2


def test_timed_out_task_reconciles_without_paid_retry(client, cloud, monkeypatch):
    monkeypatch.setattr(config, "ASR_TIMEOUT", 0)
    job = client.post("/api/transcriptions", json={"url": "https://example.com/video/1", "allow_asr": True}).json()
    value = wait(client, job["id"])
    assert value["error_code"] == "SUBMISSION_UNCERTAIN"
    assert cloud["delete"] == 0
    main.transcription_manager.reconcile()
    recovered = client.get(f"/api/transcriptions/{job['id']}").json()
    assert recovered["status"] == "done" and recovered["error"] is None
    assert cloud["submit"] == 1 and cloud["delete"] == 1


def test_media_processing_with_real_tools(monkeypatch, tmp_path):
    import shutil
    import wave
    if not shutil.which(config.FFMPEG_BINARY) or not shutil.which(config.FFPROBE_BINARY):
        pytest.skip("ffmpeg/ffprobe unavailable; configure FFMPEG_BINARY/FFPROBE_BINARY")
    source = tmp_path / "silence.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(44100)
        stream.writeframes(b"\0" * 44100 * 2 * 2 * 2)
    assert transcriptions.probe_audio(source) == pytest.approx(2, abs=0.01)
    monkeypatch.setattr(downloader, "download", lambda *a, **k: source)
    path, duration = transcriptions.acquire_audio("https://example.com/1", tmp_path, lambda **f: None)
    assert path.suffix == ".mp3" and path.stat().st_size > 0 and duration == pytest.approx(2, abs=0.2)
    pcm = transcriptions.prepare_pcm(path)
    assert pcm.suffix == ".pcm" and pcm.stat().st_size == pytest.approx(2 * 16000 * 2, abs=1000)
    monkeypatch.setattr(config, "ASR_MAX_FILESIZE_MB", 0)
    with pytest.raises(TranscriptionError) as exc:
        transcriptions.acquire_audio("https://example.com/1", tmp_path, lambda **f: None)
    assert exc.value.code == "AUDIO_TOO_LARGE"
