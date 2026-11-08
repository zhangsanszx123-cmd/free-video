import pytest

from app import douyin, downloader
from app.errors import VideoError

DETAIL = {
    "aweme_id": "6915675899241450760",
    "desc_raw": "测试/作品 #话题",
    "nickname_raw": "小透明",
    "cover": "https://p3.douyinpic.com/c.jpeg",
    "duration": 12345,
    "images": [],
    "video_play_addr": ["https://v1.douyinvod.com/a.mp4", "https://v2.douyinvod.com/b.mp4"],
}


def test_is_douyin():
    assert douyin.is_douyin("https://v.douyin.com/iRNBho6u/")
    assert douyin.is_douyin("https://www.douyin.com/video/123")
    assert douyin.is_douyin("https://www.iesdouyin.com/share/video/123/")
    assert not douyin.is_douyin("https://www.bilibili.com/video/BV1")
    assert not douyin.is_douyin("https://notdouyin.com/x")


def test_summarize():
    s = douyin.summarize(DETAIL, "https://v.douyin.com/x/")
    assert s["platform"] == "Douyin" and s["title"] == "测试/作品 #话题" and s["uploader"] == "小透明"
    assert s["duration"] == 12.345 and s["qualities"] == [] and s["subtitles"] == []
    assert s["direct"]["url"] == "https://v1.douyinvod.com/a.mp4"
    assert s["audio_url"] == "https://v1.douyinvod.com/a.mp4"
    assert s["description"] == "测试/作品 #话题"
    assert s["tags"] == ["话题"]
    assert s["images"] == ["https://p3.douyinpic.com/c.jpeg"]
    assert s["url"] == "https://www.douyin.com/video/6915675899241450760"
    s2 = douyin.summarize({**DETAIL, "custom_cover": "https://p3.douyinpic.com/real_cover.jpeg"}, "u")
    assert s2["thumbnail"] == "https://p3.douyinpic.com/real_cover.jpeg"
    assert s2["images"] == ["https://p3.douyinpic.com/real_cover.jpeg"]
    raw = {"aweme_detail": {"video": {
        "cover": {"uri": "u1", "url_list": ["https://p3.douyinpic.com/cover_330.jpeg"]},
        "cover_original_scale": {"uri": "u1", "url_list": ["https://p3.douyinpic.com/cover_full.jpeg"]},
        "origin_cover": {"uri": "u2", "url_list": ["https://p3.douyinpic.com/frame.jpeg"]},
    }}}
    assert douyin._extract_cover(raw) == "https://p3.douyinpic.com/cover_full.jpeg"
    with pytest.raises(VideoError, match="图文"):
        douyin.summarize({**DETAIL, "images": ["https://img"]}, "u")
    with pytest.raises(VideoError, match="视频地址"):
        douyin.summarize({**DETAIL, "video_play_addr": []}, "u")


def test_friendly_error():
    assert "已删除" in douyin.friendly_error(Exception("作品 1 无法获取：因作品权限或已被删除，无法观看"))
    assert "无法识别" in douyin.friendly_error(Exception("输入的URL不合法"))
    assert "接口可能已更新" in douyin.friendly_error(Exception("403"))


def test_fetch_detail_retries_with_fresh_cookie(monkeypatch):
    calls = []

    async def fake_fetch(url, cookie):
        calls.append(cookie)
        if len(calls) == 1:
            raise RuntimeError("403")
        return DETAIL

    monkeypatch.setattr(douyin, "_fetch", fake_fetch)
    monkeypatch.setattr(douyin, "_guest_cookie", lambda refresh=False: f"c{int(refresh)}")
    assert douyin.fetch_detail("https://v.douyin.com/x/") == DETAIL
    assert calls == ["c0", "c1"]


def test_fetch_detail_no_retry_on_deleted(monkeypatch):
    calls = []

    async def fake_fetch(url, cookie):
        calls.append(1)
        raise RuntimeError("因作品权限或已被删除")

    monkeypatch.setattr(douyin, "_fetch", fake_fetch)
    monkeypatch.setattr(douyin, "_guest_cookie", lambda refresh=False: "c")
    with pytest.raises(VideoError, match="已删除"):
        douyin.fetch_detail("https://v.douyin.com/x/")
    assert len(calls) == 1


class FakeResponse:
    def __init__(self, url):
        self.url = url
        self.headers = {"content-length": "8"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if "v1" in self.url:
            import httpx
            raise httpx.HTTPStatusError("403", request=None, response=None)

    def iter_bytes(self, size):
        yield b"ftyp"
        yield b"data"


def test_download_falls_back_to_second_url(monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "fetch_detail", lambda url: DETAIL)
    monkeypatch.setattr(douyin.httpx, "stream", lambda method, url, **kw: FakeResponse(url))
    updates = []
    path = douyin.download("https://v.douyin.com/x/", tmp_path / "j", "video", report=lambda **f: updates.append(f))
    assert path.name == "测试_作品 #话题 [6915675899241450760].mp4"
    assert path.read_bytes() == b"ftypdata"
    assert updates[0]["title"] == "测试/作品 #话题"
    assert [u["progress"] for u in updates if "progress" in u] == [50.0, 99]


def test_downloader_routes_douyin(monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "parse", lambda url: {"platform": "Douyin", "url": url})
    monkeypatch.setattr(douyin, "download", lambda url, outdir, kind, report: tmp_path / "x.mp4")
    share = "3.07 复制打开抖音，看看【作品】 https://v.douyin.com/iABC/ 8@5.com"
    assert downloader.parse(share) == {"platform": "Douyin", "url": "https://v.douyin.com/iABC/"}
    assert downloader.download(share, tmp_path).name == "x.mp4"
    with pytest.raises(VideoError, match="没有字幕"):
        downloader.download_subtitle(share, tmp_path)
