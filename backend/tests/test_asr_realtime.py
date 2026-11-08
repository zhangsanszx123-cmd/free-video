import json
from queue import Empty, Queue
import threading
import time

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app import asr, asr_realtime, config, downloader, main, transcriptions
from app.asr import Recognition
from app.errors import NoSubtitles, TranscriptionError
from app.subtitles import Cue


@pytest.fixture
def key_only(monkeypatch):
    for name, value in {"ASR_PROVIDER": "paraformer-realtime", "ASR_MODEL": "paraformer-realtime-v2",
                        "DASHSCOPE_API_KEY": "test-key", "OSS_BUCKET": None, "OSS_ACCESS_KEY_ID": None,
                        "OSS_ACCESS_KEY_SECRET": None, "ASR_PRICE_PER_SECOND": "0.00024"}.items():
        monkeypatch.setattr(config, name, value)


class FakeSocket:
    def __init__(self, mode="success"):
        self.mode = mode
        self.events = Queue()
        self.sent = []
        self.task_id = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def event(self, name, payload=None):
        return json.dumps({"header": {"event": name, "task_id": self.task_id}, "payload": payload or {}})

    def send(self, value):
        self.sent.append(value)
        if isinstance(value, bytes):
            assert any(isinstance(s, str) and json.loads(s)["header"]["action"] == "run-task" for s in self.sent)
            return
        body = json.loads(value)
        action = body["header"]["action"]
        if action == "run-task":
            self.task_id = body["header"]["task_id"]
            if self.mode == "reject":
                self.events.put(self.event("task-failed"))
            elif self.mode == "wrong_id":
                self.events.put(json.dumps({"header": {"event": "task-started", "task_id": "another"}}))
            else:
                self.events.put(self.event("task-started"))
                if self.mode == "disconnect":
                    self.events.put(OSError("network error must not leak test-key"))
                elif self.mode == "early_finish":
                    self.events.put(self.event("task-finished"))
        elif action == "finish-task":
            if self.mode == "failed":
                self.events.put(self.event("task-failed"))
                return
            if self.mode != "silence":
                self.events.put(self.event("result-generated", {"output": {"sentence": {
                    "text": "临时结果不保留", "sentence_end": False, "begin_time": 0, "end_time": None}}}))
                self.events.put(self.event("result-generated", {"output": {"sentence": {
                    "text": "心跳不保留", "sentence_end": True, "heartbeat": True}}}))
                sentence = {"text": "你好，Hello world。", "sentence_end": True, "begin_time": 100, "end_time": 900}
                if self.mode == "word_times":
                    sentence.update(end_time=None, words=[{"end_time": 300}, {"end_time": 900}])
                elif self.mode == "bad_times":
                    sentence.update(end_time=None, words=[])
                for duration in (1, 2):
                    self.events.put(self.event("result-generated", {"output": {"sentence": sentence}, "usage": {"duration": duration}}))
            self.events.put(self.event("task-finished"))

    def recv(self, timeout):
        try:
            value = self.events.get(timeout=timeout)
        except Empty:
            raise TimeoutError() from None
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.parametrize("mode", ["success", "word_times", "silence", "failed", "reject"])
def test_stream_protocol(monkeypatch, tmp_path, key_only, mode):
    socket = FakeSocket(mode)
    connections, journaled = [], []
    def connect(url, **kwargs):
        connections.append((url, kwargs))
        return socket
    monkeypatch.setattr(asr_realtime, "connect", connect)
    pcm = tmp_path / "test.pcm"
    pcm.write_bytes(b"\0" * 32)
    def journal(task_id):
        assert not socket.sent  # before run-task, not after audio submission
        journaled.append(task_id)
    value = asr_realtime.ParaformerRealtime().recognize(pcm, journal, threading.Event())
    assert journaled == [socket.task_id]
    assert len(connections) == 1 and connections[0][1]["additional_headers"] == {"Authorization": "Bearer test-key"}
    run = json.loads(socket.sent[0])
    assert run["payload"]["model"] == "paraformer-realtime-v2"
    assert run["payload"]["parameters"]["format"] == "pcm"
    assert run["payload"]["input"] == {} and run["header"]["streaming"] == "duplex"
    if mode in ("success", "word_times"):
        assert value.status == "SUCCEEDED" and len(value.cues) == 1
        assert value.cues[0].end == "00:00:00,900" and value.duration == 2
        assert value.cues[0].text == "你好，Hello world。"
    elif mode == "silence":
        assert value.status == "SUCCEEDED" and value.cues == []
    else:
        assert value.status == "FAILED"


@pytest.mark.parametrize("mode", ["disconnect", "early_finish", "wrong_id", "bad_times"])
def test_invalid_or_broken_stream_never_returns_partial_success(monkeypatch, tmp_path, key_only, mode):
    socket = FakeSocket(mode)
    monkeypatch.setattr(asr_realtime, "connect", lambda *a, **k: socket)
    pcm = tmp_path / "test.pcm"
    pcm.write_bytes(b"\0" * 3200)
    with pytest.raises(TranscriptionError) as exc:
        asr_realtime.ParaformerRealtime().recognize(pcm, lambda _: None, threading.Event())
    assert "test-key" not in str(exc.value)


def test_handshake_auth_failure_has_no_submission(monkeypatch, tmp_path, key_only):
    def connect(*args, **kwargs):
        raise InvalidStatus(Response(401, "Unauthorized", Headers()))
    monkeypatch.setattr(asr_realtime, "connect", connect)
    with pytest.raises(TranscriptionError) as exc:
        asr_realtime.ParaformerRealtime().recognize(tmp_path / "not-opened.pcm", lambda _: pytest.fail("must not submit"), threading.Event())
    assert exc.value.code == "CLOUD_AUTH"


def wait(client, job_id):
    for _ in range(200):
        value = client.get(f"/api/transcriptions/{job_id}").json()
        if value["status"] in ("done", "error"):
            return value
        time.sleep(0.01)
    raise AssertionError("job timeout")


@pytest.mark.parametrize("mode", ["success", "silence", "failed", "before_submit", "after_submit"])
def test_key_only_job_and_budget(client, monkeypatch, key_only, mode):
    calls = []
    def no_sub(*args, **kwargs):
        raise NoSubtitles("无字幕")
    monkeypatch.setattr(transcriptions, "read_subtitles", no_sub)
    monkeypatch.setattr(downloader, "parse", lambda url: {"title": "仅 Key 转写", "url": url, "duration": 2})
    def audio(url, directory, report):
        path = directory / "input.mp3"
        path.write_bytes(b"source")
        return path, 2
    def pcm(path):
        target = path.with_suffix(".pcm")
        target.write_bytes(b"\0" * 32)
        return target
    monkeypatch.setattr(transcriptions, "acquire_audio", audio)
    monkeypatch.setattr(transcriptions, "prepare_pcm", pcm)
    monkeypatch.setattr(transcriptions, "TemporaryStorage", lambda: pytest.fail("must not use OSS"))
    class Stream:
        def recognize(self, path, on_submit, cancel):
            calls.append(path)
            if mode == "before_submit":
                raise TranscriptionError("CLOUD_AUTH", "无模型权限")
            on_submit("client-generated-uuid")
            if mode == "after_submit":
                raise TranscriptionError("CLOUD_NETWORK", "断线", True)
            return Recognition("FAILED" if mode == "failed" else "SUCCEEDED",
                               [] if mode == "silence" else [Cue("00:00:00,100", "00:00:01,900", "仅 Key 的文字")], 2)
    monkeypatch.setattr(asr, "get_provider", Stream)
    assert client.get("/api/health").json()["asr_enabled"] is True
    body = {"url": "https://example.com/key-only", "allow_asr": True}
    job = client.post("/api/transcriptions", json=body).json()
    result = wait(client, job["id"])
    entry = main.transcription_manager.ledger.entries()[job["id"]]
    assert entry["object_key"] is None and entry["transport"] == "stream"
    assert not calls[0].exists()  # local PCM is removed after terminal result
    if mode == "success":
        assert result["status"] == "done" and result["result"]["source"] == "asr"
        for ext in ("txt", "srt"):
            assert client.get(f"/api/transcriptions/{job['id']}/file?format={ext}").status_code == 200
        assert client.post("/api/transcriptions", json=body).json()["id"] == job["id"] and len(calls) == 1
        assert entry["charged"] == "0.00048" and entry["state"] == "settled"
    elif mode == "before_submit":
        assert entry["state"] == "released" and result["error_code"] == "CLOUD_AUTH"
    elif mode == "after_submit":
        assert entry["state"] == "unknown" and not result["retryable"]
        assert client.post("/api/transcriptions", json=body).json()["id"] == job["id"] and len(calls) == 1
    else:
        assert entry["state"] == "settled" and result["status"] == "error"


def test_restart_does_not_query_or_replay_stream(monkeypatch, key_only):
    manager = main.transcription_manager
    manager.ledger.reserve("stream", 10, None, "fingerprint")
    manager.ledger.update("stream", state="submitting", task_id="client-uuid")
    monkeypatch.setattr(asr, "get_provider", lambda: pytest.fail("stream cannot be queried or replayed"))
    manager.reconcile()
    entry = manager.ledger.entries()["stream"]
    assert entry["state"] == "unknown" and entry["object_key"] is None
    with pytest.raises(TranscriptionError):
        manager.ledger.reserve("again", 10, None, "fingerprint")


def test_real_local_websocket_exchange(monkeypatch, tmp_path, key_only):
    """Exercise the real pinned websockets library, not a mocked transport."""
    from websockets.sync.server import serve
    received = []
    def handler(connection):
        assert connection.request.headers["Authorization"] == "Bearer test-key"
        run = json.loads(connection.recv())
        task_id = run["header"]["task_id"]
        connection.send(json.dumps({"header": {"task_id": task_id, "event": "task-started"}}))
        while True:
            data = connection.recv()
            if isinstance(data, bytes):
                received.append(data)
                continue
            assert json.loads(data)["header"]["action"] == "finish-task"
            break
        for name, payload in [
            ("result-generated", {"output": {"sentence": {"sentence_end": True, "begin_time": 0,
                                                           "end_time": 100, "text": "本地协议测试"}},
                                  "usage": {"duration": 1}}),
            ("task-finished", {}),
        ]:
            connection.send(json.dumps({"header": {"task_id": task_id, "event": name}, "payload": payload}))
    pcm = tmp_path / "audio.pcm"
    pcm.write_bytes(b"\0" * 3200)
    with serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(config, "DASHSCOPE_WS_URL", f"ws://127.0.0.1:{server.socket.getsockname()[1]}")
        try:
            result = asr_realtime.ParaformerRealtime().recognize(pcm, lambda _: None, threading.Event())
            assert result.status == "SUCCEEDED" and result.cues[0].text == "本地协议测试"
            assert b"".join(received) == pcm.read_bytes() and result.duration == 1
        finally:
            server.shutdown()
            thread.join(timeout=3)
