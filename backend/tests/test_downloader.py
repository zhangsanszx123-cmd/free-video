import pytest
from yt_dlp.utils import DownloadError

from app import downloader
from app.downloader import VideoError
from app.subtitles import parse_srt, to_plain_text, to_srt

INFO = {
    "id": "BV1xx",
    "title": "测试视频 #科技 #AI",
    "description": "这是视频简介正文 #深度学习",
    "tags": ["Python", "科技"],
    "webpage_url": "https://www.bilibili.com/video/BV1xx",
    "extractor_key": "BiliBili",
    "duration": 100,
    "thumbnail": "https://img/x.jpg",
    "formats": [
        {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "ext": "m4a", "url": "u-a", "protocol": "https"},
        {"format_id": "720", "height": 720, "vcodec": "avc1", "acodec": "none", "tbr": 1000, "url": "u", "protocol": "https"},
        {"format_id": "1080", "height": 1080, "vcodec": "avc1", "acodec": "none", "filesize": 5_000_000, "url": "u", "protocol": "https"},
        {"format_id": "p360", "height": 360, "vcodec": "avc1", "acodec": "mp4a", "ext": "mp4", "url": "direct-360", "protocol": "https"},
        {"format_id": "p480", "height": 480, "vcodec": "avc1", "acodec": "mp4a", "ext": "mp4", "url": "direct-480",
         "protocol": "https", "http_headers": {"Referer": "https://bilibili.com"}},
    ],
    "subtitles": {"danmaku": [{}], "zh-CN": [{"name": "中文"}]},
    "automatic_captions": {"en": [{"name": "English"}], "fr": [{}]},
}


def test_extract_url_from_share_text():
    text = "3.07 复制打开抖音，看看【某某的作品】好看 https://v.douyin.com/iABCdef/ 8@5.com :2pm"
    assert downloader.extract_url(text) == "https://v.douyin.com/iABCdef/"
    assert downloader.extract_url("【标题】https://b23.tv/abc123，快来看") == "https://b23.tv/abc123"
    with pytest.raises(VideoError):
        downloader.extract_url("no link here")


def test_summarize_qualities_direct_and_subs():
    s = downloader.summarize(INFO)
    assert [q["label"] for q in s["qualities"]] == ["1080P", "720P", "480P", "360P"]
    assert s["qualities"][0]["pro"] and s["qualities"][0]["size"] == 5_000_000
    assert s["qualities"][1]["size"] == 1000 * 125 * 100
    assert s["direct"]["url"] == "direct-360"  # 480 needs Referer -> skipped
    assert s["audio_url"] == "u-a"
    assert s["description"] == "这是视频简介正文 #深度学习"
    assert s["tags"] == ["科技", "AI", "深度学习", "Python"]
    assert s["images"] == ["https://img/x.jpg"]
    assert s["has_audio"]
    langs = {x["lang"]: x["auto"] for x in s["subtitles"]}
    assert langs == {"zh-CN": False, "en": True}
    assert downloader.choose_subtitle(INFO) == "zh-CN"


def test_no_direct_for_youtube():
    assert downloader.summarize({**INFO, "extractor_key": "Youtube"})["direct"] is None


def test_playlist_takes_first_entry():
    assert downloader._first_entry({"_type": "playlist", "entries": [None, INFO]})["id"] == "BV1xx"


class FakeYDL:
    raise_error = None
    last_opts = None

    def __init__(self, opts):
        FakeYDL.last_opts = opts
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if self.raise_error:
            raise self.raise_error
        return {**INFO, "requested_formats": [{}, {}]}

    def process_ie_result(self, info, download=True):
        outtmpl = self.opts["outtmpl"]
        for hook in self.opts.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished"})
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished"})
        for hook in self.opts.get("postprocessor_hooks", []):
            hook({"status": "started", "postprocessor": "Merger"})
        from pathlib import Path
        ext = "srt" if self.opts.get("writesubtitles") else ("mp3" if "postprocessors" in self.opts else "mp4")
        Path(outtmpl.replace("%(title).80B [%(id)s].%(ext)s", f"测试视频 #科技 #AI [BV1xx].{ext}")).write_bytes(b"x" * 10)
        return info


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYDL.raise_error = None
    monkeypatch.setattr(downloader, "YoutubeDL", FakeYDL)
    return FakeYDL


def test_download_video_progress_and_format(fake_ydl, tmp_path):
    updates = []
    path = downloader.download("https://b23.tv/x", tmp_path / "j", 720, "video", report=lambda **f: updates.append(f))
    assert path.name == "测试视频 #科技 #AI [BV1xx].mp4"
    assert fake_ydl.last_opts["format"].startswith("bv*[height<=720]+ba")
    assert fake_ydl.last_opts["merge_output_format"] == "mp4"
    progress = [u["progress"] for u in updates if "progress" in u]
    assert progress == [25.0, 75.0]
    assert any(u.get("status") == "processing" for u in updates)


def test_metadata_explicitly_requests_subtitles(fake_ydl):
    downloader.extract_info("https://www.bilibili.com/video/BV1xx")
    assert fake_ydl.last_opts["writesubtitles"] is True
    assert fake_ydl.last_opts["writeautomaticsub"] is True
    assert fake_ydl.last_opts["skip_download"] is True


def test_login_required_subtitle_message(monkeypatch, tmp_path):
    class LockedYDL(FakeYDL):
        def extract_info(self, url, download=False):
            self.opts["logger"].warning("Subtitles are only available when logged in. Use cookies.")
            return {**INFO, "subtitles": {}, "automatic_captions": {}}
    monkeypatch.setattr(downloader, "YoutubeDL", LockedYDL)
    info = downloader.extract_info("https://www.bilibili.com/video/BV1xx")
    assert info["subtitle_login_required"] is True
    assert downloader.summarize(info)["subtitle_notice"] == downloader.SUBTITLE_LOGIN_MESSAGE
    assert downloader.summarize(INFO)["subtitle_notice"] is None
    from app.errors import NoSubtitles
    with pytest.raises(NoSubtitles, match="需要登录 B 站"):
        downloader.download_subtitle("https://www.bilibili.com/video/BV1xx", tmp_path)


def test_download_audio_mp3(fake_ydl, tmp_path):
    path = downloader.download("https://b23.tv/x", tmp_path / "j", None, "audio")
    assert path.suffix == ".mp3"
    assert fake_ydl.last_opts["postprocessors"][0]["preferredcodec"] == "mp3"


def test_download_subtitle(fake_ydl, tmp_path):
    path, info = downloader.download_subtitle("https://b23.tv/x", tmp_path / "s")
    assert path.suffix == ".srt"
    assert fake_ydl.last_opts["subtitleslangs"] == ["zh-CN"]


def test_friendly_errors(fake_ydl):
    fake_ydl.raise_error = DownloadError("ERROR: [generic] Unsupported URL: https://x.com")
    with pytest.raises(VideoError, match="暂不支持"):
        downloader.parse("https://x.com")
    fake_ydl.raise_error = DownloadError("ERROR: Fresh cookies are needed")
    with pytest.raises(VideoError, match="登录"):
        downloader.parse("https://www.xiaohongshu.com/explore/x")
    fake_ydl.raise_error = DownloadError("ERROR: [BiliBili] 1zz: An extractor error has occurred. (caused by KeyError('bvid')); please report this issue on https://github.com/yt-dlp/yt-dlp/issues")
    with pytest.raises(VideoError, match="链接无效"):
        downloader.parse("https://www.bilibili.com/video/BV1zz")


def test_srt_roundtrip():
    srt = "\ufeff1\n00:00:01,000 --> 00:00:02,000\n<i>hello</i>\n\n2\n00:00:02,000 --> 00:00:03,000\nhello\n\n3\n00:00:03,000 --> 00:00:04,500\nworld\n"
    cues = parse_srt(srt)
    assert [(c.text, c.end) for c in cues] == [("hello", "00:00:03,000"), ("world", "00:00:04,500")]
    assert to_plain_text(cues) == "[00:00:01] hello\n[00:00:03] world"
    out = to_srt(cues, ["你好", "世界"])
    assert "hello\n你好" in out and out.startswith("1\n00:00:01,000 --> 00:00:03,000")
