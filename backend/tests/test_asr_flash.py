import json
from pathlib import Path
import threading
import time

import httpx
import pytest

from app import asr, asr_flash, config, downloader, main, transcriptions
from app.asr import Recognition
from app.errors import NoSubtitles, TranscriptionError
from app.subtitles import Cue


def wait(client, job_id):
    for _ in range(200):
        result = client.get(f"/api/transcriptions/{job_id}").json()
        if result["status"] in ("done", "error"):
            return result
        time.sleep(0.01)
    raise AssertionError("job timeout")


@pytest.fixture
def flash(monkeypatch):
    for name, value in {"ASR_PROVIDER": "fun-asr-flash", "ASR_MODEL": "fun-asr-flash-2026-06-15",
                        "DASHSCOPE_API_KEY": "test-key", "ASR_PRICE_PER_SECOND": "0.00022",
                        "OSS_BUCKET": None, "OSS_ACCESS_KEY_ID": None, "OSS_ACCESS_KEY_SECRET": None}.items():
        monkeypatch.setattr(config, name, value)


def sentence(text="你好。", start=100, end=900):
    return {"begin_time": start, "end_time": end, "sentence_end": True, "text": text,
            "words": [{"begin_time": start, "end_time": end, "text": text, "punctuation": ""}]}


def test_cumulative_snapshots_and_distinct_sentences():
    first = sentence("你好。")
    cumulative = sentence("你好。世界。", end=1900)
    cumulative["words"] = first["words"] + sentence("世界。", 1000, 1900)["words"]
    tail = sentence("结束。", 2000, 2900)
    cues = asr_flash.snapshot_cues([first, cumulative, tail], "你好。世界。结束。", 280000)
    assert "".join(c.text for c in cues) == "你好。世界。结束。"
    assert cues[0].start == "00:04:40,100" and cues[-1].end == "00:04:42,900"


@pytest.mark.parametrize("mode", ["success", "silence", "auth", "broken", "partial", "invalid"])
def test_http_protocol(monkeypatch, tmp_path, flash, mode):
    calls, journal = [], []
    event = {"output": {"text": "你好。", "sentence": sentence()}, "usage": {"duration": 2}}
    if mode == "silence":
        event["output"] = {"text": "", "sentence": sentence("")}
    if mode == "partial":
        event["output"]["sentence"]["sentence_end"] = False
    if mode == "invalid":
        event["output"]["sentence"]["words"][0]["end_time"] = -1
    real_stream = httpx.stream
    def handler(request):
        assert journal and len(calls) == 0
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "fun-asr-flash-2026-06-15"
        assert body["input"]["messages"][0]["content"][0]["input_audio"]["data"] == "data:audio/mp3;base64,YXVkaW8="
        if mode == "broken":
            raise httpx.ReadError("test-key must not leak")
        return httpx.Response(401 if mode == "auth" else 200,
                              content=("data:" + json.dumps(event) + "\n\n").encode())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(asr_flash.httpx, "stream", client.stream)
    path = tmp_path / "input.mp3"
    path.write_bytes(b"audio")
    try:
        if mode in ("success", "silence"):
            result = asr_flash.FunASRFlash().recognize(path, journal.append, threading.Event(), duration=2)
            assert result.duration == 2
            assert bool(result.cues) == (mode == "success")
        else:
            with pytest.raises(TranscriptionError) as exc:
                asr_flash.FunASRFlash().recognize(path, journal.append, threading.Event(), duration=2)
            assert "test-key" not in str(exc.value)
        assert len(calls) == 1
    finally:
        client.close()
        monkeypatch.setattr(asr_flash.httpx, "stream", real_stream)


@pytest.mark.parametrize("mode", ["success", "auth", "broken"])
def test_flash_job_budget_exports_and_no_oss(client, monkeypatch, flash, mode):
    def no_sub(*args, **kwargs):
        raise NoSubtitles("无字幕")
    monkeypatch.setattr(transcriptions, "read_subtitles", no_sub)
    monkeypatch.setattr(downloader, "parse", lambda url: {"title": "快速识别", "url": url, "duration": 2})
    def audio(url, directory, report):
        path = directory / "input.mp3"
        path.write_bytes(b"audio")
        return path, 2
    monkeypatch.setattr(transcriptions, "acquire_audio", audio)
    monkeypatch.setattr(transcriptions, "TemporaryStorage", lambda: pytest.fail("no OSS"))
    calls = []
    class Provider:
        def recognize(self, path, on_submit, cancel, **kwargs):
            calls.append(path)
            on_submit("request")
            if mode != "success":
                raise TranscriptionError("CLOUD_AUTH" if mode == "auth" else "CLOUD_NETWORK", "失败")
            return Recognition("SUCCEEDED", [Cue("00:00:00,100", "00:00:01,900", "快速文字")], 2)
    monkeypatch.setattr(asr, "get_provider", Provider)
    assert asr.enabled()
    body = {"url": "https://example.com/flash", "allow_asr": True}
    job = client.post("/api/transcriptions", json=body).json()
    result = wait(client, job["id"])
    entry = main.transcription_manager.ledger.entries()[job["id"]]
    assert entry["transport"] == "direct-http" and entry["object_key"] is None
    assert entry["state"] == {"success": "settled", "auth": "released", "broken": "unknown"}[mode]
    assert not calls[0].exists()
    if mode == "success":
        assert result["status"] == "done" and entry["charged"] == "0.00044"
        assert client.get(f"/api/transcriptions/{job['id']}/file?format=srt").status_code == 200
    if mode != "auth":
        assert client.post("/api/transcriptions", json=body).json()["id"] == job["id"]
        assert len(calls) == 1


@pytest.mark.parametrize('ending', ['normal', 'metadata', 'disconnect', 'unfinished', 'empty'])
def test_shorter_usage_does_not_mean_incomplete_audio(monkeypatch, tmp_path, flash, ending):
    event = {'output': {'text': '完整文字。', 'sentence': sentence('完整文字。', 100, 98380)},
             'usage': {'duration': 98}}
    if ending == 'unfinished':
        event['output']['sentence']['sentence_end'] = False
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            if ending == 'empty':
                return
            yield ('data:' + json.dumps(event) + '\n\n').encode()
            if ending == 'disconnect':
                raise httpx.ReadError('private response must not leak')
            if ending == 'metadata':
                yield b'data:{"usage":{"duration":98}}\n\n'
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Body())))
    monkeypatch.setattr(asr_flash.httpx, 'stream', client.stream)
    audio = tmp_path / 'input.mp3'
    audio.write_bytes(b'audio')
    try:
        if ending in ('normal', 'metadata'):
            result = asr_flash.FunASRFlash().recognize(audio, lambda _: None, threading.Event(), duration=109.017688)
            assert result.status == 'SUCCEEDED' and result.duration == 98
            assert ''.join(c.text for c in result.cues) == '完整文字。'
        else:
            with pytest.raises(TranscriptionError) as exc:
                asr_flash.FunASRFlash().recognize(audio, lambda _: None, threading.Event(), duration=109.017688)
            assert exc.value.code == 'CLOUD_NETWORK'
    finally:
        client.close()


def test_restart_keeps_direct_hold(monkeypatch, flash):
    manager = main.transcription_manager
    manager.ledger.reserve("flash", 2, None, "same-video")
    manager.ledger.update("flash", state="submitting")
    monkeypatch.setattr(asr, "get_provider", lambda: pytest.fail("must not query HTTP request id"))
    manager.reconcile()
    assert manager.ledger.entries()["flash"]["state"] == "unknown"


def test_recorded_real_response():
    # Optional local regression from the previously authorized real request; no API call.
    path = Path(__file__).resolve().parents[2] / ".runtime/fast-asr-sample/raw_events.json"
    if not path.exists():
        pytest.skip("local sample unavailable")
    events = json.loads(path.read_text(encoding="utf-8"))
    sentences = [e["output"]["sentence"] for e in events if e.get("output", {}).get("sentence", {}).get("sentence_end")]
    text = events[-1]["output"]["text"]
    cues = asr_flash.snapshot_cues(sentences, text)
    assert "".join(c.text for c in cues) == text and len(text) == 2039
    assert cues[-1].end == "00:04:47,300"


def test_exact_sample_segments(monkeypatch, tmp_path):
    import wave
    source = tmp_path / "input.mp3"
    pcm = tmp_path / "input.pcm"
    # Three segments, exact sample counts and offsets; includes a partial final second.
    data = b"\x01\x02" * (561 * 16000 + 8000)
    pcm.write_bytes(data)
    monkeypatch.setattr(transcriptions, "prepare_pcm", lambda _: pcm)
    segments = transcriptions.prepare_segments(source, 561.5)
    assert [d for _, d, _ in segments] == [280, 280, 1.5]
    assert [offset for _, _, offset in segments] == [0, 280000, 560000]
    rebuilt = b""
    for path, _, _ in segments:
        with wave.open(str(path), "rb") as audio:
            assert audio.getframerate() == 16000 and audio.getnchannels() == 1
            rebuilt += audio.readframes(audio.getnframes())
    assert rebuilt == data  # no missing/overlapping samples


@pytest.mark.parametrize("mode", ["success", "rejected", "uncertain", "budget"])
def test_parallel_long_video(client, monkeypatch, flash, mode):
    def no_sub(*args, **kwargs):
        raise NoSubtitles("无字幕")
    monkeypatch.setattr(transcriptions, "read_subtitles", no_sub)
    monkeypatch.setattr(downloader, "parse", lambda url: {"title": "长视频", "url": url, "duration": 560})
    monkeypatch.setattr(transcriptions, "acquire_audio", lambda url, directory, report: (directory / "input.mp3", 560))
    monkeypatch.setattr(transcriptions, "prepare_segments", lambda path, duration:
                        [(path, 280, 0), (path, 280, 280000)])
    if mode == "budget":
        monkeypatch.setattr(config, "ASR_DAILY_BUDGET", "0.01")
    barrier = threading.Barrier(2)
    calls = []
    class Provider:
        def recognize(self, path, on_submit, cancel, duration, offset_ms):
            calls.append(offset_ms)
            on_submit(str(offset_ms))
            barrier.wait(timeout=2)  # proves concurrent requests, not sequential processing
            if offset_ms and mode in ("rejected", "uncertain"):
                raise TranscriptionError("CLOUD_AUTH" if mode == "rejected" else "CLOUD_NETWORK", "失败")
            return Recognition("SUCCEEDED", [Cue("00:04:40,000" if offset_ms else "00:00:00,000",
                                                  "00:04:41,000" if offset_ms else "00:00:01,000",
                                                  "后段" if offset_ms else "前段")], 279.2)
    monkeypatch.setattr(asr, "get_provider", Provider)
    body = {"url": "https://example.com/long", "allow_asr": True}
    job = client.post("/api/transcriptions", json=body).json()
    result = wait(client, job["id"])
    entries = main.transcription_manager.ledger.entries()
    if mode == "budget":
        assert result["error_code"] == "BUDGET_EXCEEDED" and not calls and not entries
        return
    entry = entries[job["id"]]
    assert len(calls) == 2
    if mode == "success":
        assert result["status"] == "done" and result["result"]["text"] == "前段\n后段"
        assert "00:04:40,000" in result["result"]["srt"]
        assert entry["charged"] == "0.12320"  # per-segment rounding, 280*2 seconds
    elif mode == "rejected":
        assert result["error_code"] == "PARTIAL_RECOGNITION" and not result["retryable"]
        assert entry["state"] == "settled" and entry["charged"] == "0.06160"
    else:
        assert result["error_code"] == "SUBMISSION_UNCERTAIN" and entry["state"] == "unknown"
    assert client.post("/api/transcriptions", json=body).json()["id"] == job["id"]
