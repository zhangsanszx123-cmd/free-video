import time
import zipfile

from app import ai, config, downloader, main, tasks
from app.downloader import VideoError
from app.subtitles import Cue

from .conftest import wait_job


def fake_download(text, outdir, quality=None, kind="video", report=lambda **_: None):
    if "bad" in text:
        raise VideoError("视频不存在或已被删除")
    outdir.mkdir(parents=True, exist_ok=True)
    report(status="running", progress=50, title="T")
    p = outdir / ("a.mp3" if kind == "audio" else "a.mp4")
    p.write_bytes(b"data")
    return p


def test_health(client):
    assert client.get("/api/health").json()["ok"]


def test_parse_ok_and_error(client, monkeypatch):
    monkeypatch.setattr(downloader, "parse", lambda u: {"title": "ok"})
    assert client.post("/api/parse", json={"url": "https://b23.tv/x"}).json() == {"title": "ok"}

    def boom(u):
        raise VideoError("暂不支持该链接")
    monkeypatch.setattr(downloader, "parse", boom)
    r = client.post("/api/parse", json={"url": "https://x"})
    assert r.status_code == 400 and r.json()["detail"] == "暂不支持该链接"


def test_download_job_and_file(client, monkeypatch):
    monkeypatch.setattr(downloader, "download", fake_download)
    assert client.post("/api/download", json={"url": "nothing"}).status_code == 400
    job = client.post("/api/download", json={"url": "分享 https://b23.tv/x", "quality": 720}).json()
    data = wait_job(client, job["id"])
    assert data["status"] == "done" and data["ready"] and data["filename"] == "a.mp4"
    r = client.get(f"/api/jobs/{job['id']}/file")
    assert r.status_code == 200 and r.content == b"data"
    assert client.get("/api/jobs/nope").status_code == 404


def test_download_job_error(client, monkeypatch):
    monkeypatch.setattr(downloader, "download", fake_download)
    job = client.post("/api/download", json={"url": "https://bad.com/v"}).json()
    data = wait_job(client, job["id"])
    assert data["status"] == "error" and "不存在" in data["error"]
    assert client.get(f"/api/jobs/{job['id']}/file").status_code == 404


def test_batch_zip_with_partial_failure(client, monkeypatch):
    monkeypatch.setattr(downloader, "download", fake_download)
    urls = ["https://a.com/1\nhttps://a.com/2", "https://a.com/1", "https://bad.com/3"]
    job = client.post("/api/batch", json={"urls": urls, "kind": "audio"}).json()
    data = wait_job(client, job["id"])
    assert data["status"] == "done"
    assert [i["status"] for i in data["items"]] == ["done", "done", "error"]
    r = client.get(f"/api/jobs/{job['id']}/file")
    path = config.DOWNLOAD_DIR / job["id"] / data["filename"]
    assert r.status_code == 200 and sorted(zipfile.ZipFile(path).namelist()) == ["01_a.mp3", "02_a.mp3"]


def test_batch_limits(client, monkeypatch):
    assert client.post("/api/batch", json={"urls": ["x"]}).status_code == 400
    monkeypatch.setattr(config, "MAX_BATCH", 1)
    assert client.post("/api/batch", json={"urls": ["https://a/1 https://a/2"]}).status_code == 400


def test_subtitle_job(client, monkeypatch):
    def fake_sub(text, outdir, lang=None):
        outdir.mkdir(parents=True, exist_ok=True)
        p = outdir / f"t.{lang}.srt"
        p.write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n", encoding="utf-8")
        return p, {"title": "T"}
    monkeypatch.setattr(downloader, "download_subtitle", fake_sub)
    job = client.post("/api/subtitles", json={"url": "https://b23.tv/x", "lang": "en"}).json()
    data = wait_job(client, job["id"])
    assert data["filename"] == "t.en.srt" and data["title"] == "T"


def test_transcript_endpoint(client, monkeypatch):
    def fake_sub(text, outdir, lang=None):
        outdir.mkdir(parents=True, exist_ok=True)
        p = outdir / "t.srt"
        p.write_text("1\n00:00:01,000 --> 00:00:02,000\n第一句台词\n\n2\n00:00:02,500 --> 00:00:04,000\n第二句台词\n", encoding="utf-8")
        return p, {"title": "T"}
    monkeypatch.setattr(downloader, "download_subtitle", fake_sub)
    r = client.post("/api/transcript", json={"url": "https://b23.tv/x"})
    assert r.status_code == 200
    body = r.json()
    assert body["cues"] == 2
    assert "第一句台词" in body["text"] and "第二句台词" in body["text"]
    assert "[00:00:01]" in body["timed_text"]

    def no_sub(text, outdir, lang=None):
        raise VideoError("该视频没有可用字幕")
    monkeypatch.setattr(downloader, "download_subtitle", no_sub)
    r2 = client.post("/api/transcript", json={"url": "https://b23.tv/x"})
    assert r2.status_code == 400 and "没有可用字幕" in r2.json()["detail"]


def test_ai_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", None)
    assert client.post("/api/ai/summary", json={"url": "https://b23.tv/x"}).status_code == 503
    assert client.post("/api/ai/translate", json={"url": "https://b23.tv/x"}).status_code == 503


def test_ai_summary_sse(client, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(tasks, "fetch_transcript", lambda u, d: ({"title": "T"}, [Cue("00:00:01,000", "00:00:02,000", "hi")]))
    monkeypatch.setattr(ai, "summarize_stream", lambda title, text: iter(["## 总结", " 好"]))
    body = client.post("/api/ai/summary", json={"url": "https://b23.tv/x"}).text
    assert 'event: delta\ndata: "## 总结"' in body and "event: done" in body


def test_ai_summary_sse_error(client, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")

    def no_subs(u, d):
        raise VideoError("该视频没有可用字幕")
    monkeypatch.setattr(tasks, "fetch_transcript", no_subs)
    body = client.post("/api/ai/summary", json={"url": "https://b23.tv/x"}).text
    assert 'event: error\ndata: "该视频没有可用字幕"' in body


def test_ai_translate_job(client, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    cues = [Cue("00:00:01,000", "00:00:02,000", "hello"), Cue("00:00:02,000", "00:00:03,000", "world")]
    monkeypatch.setattr(tasks, "fetch_transcript", lambda u, d: ({"title": "My/Video"}, cues))

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    class R:
                        choices = [type("C", (), {"message": type("M", (), {"content": "0|你好\n1|世界"})()})()]
                    return R()
    monkeypatch.setattr(ai, "_client", lambda: FakeClient)
    job = client.post("/api/ai/translate", json={"url": "https://b23.tv/x", "target_lang": "简体中文"}).json()
    data = wait_job(client, job["id"])
    assert data["status"] == "done" and data["filename"] == "My_Video.双语.简体中文.srt"
    text = client.get(f"/api/jobs/{job['id']}/file").text
    assert "hello\n你好" in text and "world\n世界" in text
    assert config.DEEPSEEK_MODEL == "deepseek-flash"
    assert ai._extra_kwargs("deepseek-flash") == {"extra_body": {"thinking": {"type": "disabled"}}}


def test_cleanup_removes_expired(client, monkeypatch):
    monkeypatch.setattr(downloader, "download", fake_download)
    job = client.post("/api/download", json={"url": "https://b23.tv/x"}).json()
    wait_job(client, job["id"])
    main.manager.cleanup(now=time.time() + config.FILE_TTL_SECONDS + 10)
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert not (config.DOWNLOAD_DIR / job["id"]).exists()
