import pytest

from app import bilibili_subs, downloader
from app.errors import NoSubtitles, VideoError

VIEW = {"code": 0, "data": {"aid": 111, "pages": [{"page": 1, "cid": 901}, {"page": 2, "cid": 902}]}}


def dm_view(*tracks):
    return {"code": 0, "data": {"subtitle": {"subtitles": list(tracks)}}}


def track(lan, doc, url, type_=0, ai_type=0):
    return {"lan": lan, "lan_doc": doc, "subtitle_url": url, "type": type_, "ai_type": ai_type}


BODY = {"body": [{"from": 0, "to": 3, "content": "第一句"}, {"from": 3.5, "to": 4.6254, "content": "  第二句  "}, {"from": 5, "to": 6, "content": " "}]}


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise bilibili_subs.httpx.HTTPStatusError("x", request=None, response=None)


@pytest.fixture
def api(monkeypatch):
    calls = []
    routes = {
        "web-interface/view": Resp(VIEW),
        "v2/dm/view": Resp(dm_view(
            track("zh", "中文", "http://aisubtitle.hdslb.com/bfs/subtitle/a.json?auth_key=k"),
            track("ai-zh", "中文（自动生成）", "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/b?auth_key=k", 1),
            track("ai-ja", "日文（自动翻译）", "http://aisubtitle.hdslb.com/bfs/ai_subtitle/prod/c", 1, 1),
            track("zh-empty", "无地址", ""),
        )),
        "subtitle/a.json": Resp(BODY),
        "ai_subtitle/prod/b": Resp(BODY),
    }

    def fake_get(url, **kw):
        calls.append((url, kw))
        for key, resp in routes.items():
            if key in url:
                return resp
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(bilibili_subs.httpx, "get", fake_get)
    fake_get.routes, fake_get.calls = routes, calls
    return fake_get


INFO = {"id": "BV1mAAmzqEfP", "extractor_key": "BiliBili", "title": "t"}


def test_tracks_skip_machine_translation_and_empty_url(api):
    t = bilibili_subs.tracks(INFO)
    assert set(t) == {"zh", "ai-zh"}
    assert t["zh"] == {"name": "中文", "auto": False, "url": "https://aisubtitle.hdslb.com/bfs/subtitle/a.json?auth_key=k"}
    assert t["ai-zh"]["auto"] is True and t["ai-zh"]["url"].startswith("https://aisubtitle.hdslb.com/")


def test_requests_carry_no_cookie(api):
    bilibili_subs.tracks(INFO)
    for _, kw in api.calls:
        headers = {k.lower() for k in kw.get("headers", {})}
        assert "cookie" not in headers and "referer" in headers and not kw.get("cookies")


def test_multipart_uses_matching_cid(api):
    bilibili_subs.tracks({**INFO, "id": "BV1mAAmzqEfP_p2"})
    dm = next(kw for url, kw in api.calls if "dm/view" in url)
    assert dm["params"]["oid"] == 902 and dm["params"]["pid"] == 111
    view = next(kw for url, kw in api.calls if "web-interface/view" in url)
    assert view["params"]["bvid"] == "BV1mAAmzqEfP"


def test_failures_return_empty(api):
    api.routes["v2/dm/view"] = Resp({"code": -400, "message": "bad"})
    assert bilibili_subs.tracks(INFO) == {}
    api.routes["web-interface/view"] = Resp({}, 500)
    assert bilibili_subs.tracks(INFO) == {}


def test_network_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise bilibili_subs.httpx.ConnectError("down")

    monkeypatch.setattr(bilibili_subs.httpx, "get", boom)
    assert bilibili_subs.tracks(INFO) == {}


def test_non_bilibili_is_ignored(api):
    assert bilibili_subs.tracks({"id": "x", "extractor_key": "Youtube"}) == {}
    assert api.calls == []


def test_untrusted_host_is_rejected(api):
    api.routes["v2/dm/view"] = Resp(dm_view(track("zh", "中文", "http://127.0.0.1:8000/secret.json")))
    assert bilibili_subs.tracks(INFO) == {}


def test_to_srt():
    srt = bilibili_subs.to_srt_text(BODY["body"])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:03,000\n第一句\n")
    assert "2\n00:00:03,500 --> 00:00:04,625\n第二句\n" in srt
    assert "第三" not in srt and "\n3\n" not in srt


def test_download_writes_srt(api, tmp_path):
    t = bilibili_subs.tracks(INFO)["zh"]
    path = bilibili_subs.download(t, tmp_path / "out", {**INFO, "title": 'a/b:c'}, "zh")
    assert path.suffix == ".srt" and path.read_text(encoding="utf-8").count("-->") == 2
    assert "/" not in path.name and ":" not in path.name


def test_download_empty_body_raises(api, tmp_path):
    api.routes["subtitle/a.json"] = Resp({"body": []})
    t = bilibili_subs.tracks(INFO)["zh"]
    with pytest.raises(VideoError):
        bilibili_subs.download(t, tmp_path, INFO, "zh")


def locked_info(monkeypatch, found):
    monkeypatch.setattr(downloader, "extract_info", lambda text, **o: info_with(found))


def info_with(found):
    return {"id": "BV1", "title": "t", "extractor_key": "BiliBili", "subtitles": {"danmaku": [{"ext": "xml"}]},
            "bilibili_subtitles": found, "subtitle_login_required": not found}


def test_list_subtitles_includes_bilibili_tracks():
    found = {"zh": {"name": "中文", "auto": False, "url": "u"}, "ai-zh": {"name": "中文（自动生成）", "auto": True, "url": "u"}}
    subs = downloader.list_subtitles(info_with(found))
    assert [(s["lang"], s["auto"]) for s in subs] == [("zh", False), ("ai-zh", True)]
    assert downloader.choose_subtitle(info_with(found)) == "zh"


def test_extract_info_fallback_on_login_required(monkeypatch):
    class LockedYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            self.opts["logger"].warning("Subtitles are only available when logged in")
            return dict(INFO)

    monkeypatch.setattr(downloader, "YoutubeDL", LockedYDL)
    monkeypatch.setattr(bilibili_subs, "tracks", lambda info: {"zh": {"name": "中文", "auto": False, "url": "u"}})
    info = downloader.extract_info("https://www.bilibili.com/video/BV1")
    assert info["bilibili_subtitles"]["zh"]["url"] == "u"
    assert not info.get("subtitle_login_required")
    assert downloader.summarize(info)["subtitle_notice"] is None
    assert downloader.summarize(info)["default_subtitle"] == "zh"


def test_extract_info_keeps_login_notice_when_fallback_fails(monkeypatch):
    class LockedYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            self.opts["logger"].warning("Subtitles are only available when logged in")
            return dict(INFO)

    monkeypatch.setattr(downloader, "YoutubeDL", LockedYDL)
    monkeypatch.setattr(bilibili_subs, "tracks", lambda info: {})
    info = downloader.extract_info("https://www.bilibili.com/video/BV1")
    assert info["subtitle_login_required"] is True
    assert downloader.summarize(info)["subtitle_notice"] == downloader.SUBTITLE_LOGIN_MESSAGE


def test_download_subtitle_uses_bilibili_track(monkeypatch, tmp_path):
    found = {"zh": {"name": "中文", "auto": False, "url": "u"}}
    locked_info(monkeypatch, found)
    seen = {}

    def fake_download(track, outdir, info, lang):
        seen.update(track=track, lang=lang)
        outdir.mkdir(parents=True, exist_ok=True)
        p = outdir / "x.srt"
        p.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
        return p

    monkeypatch.setattr(bilibili_subs, "download", fake_download)
    path, info = downloader.download_subtitle("https://www.bilibili.com/video/BV1", tmp_path)
    assert path.name == "x.srt" and seen["lang"] == "zh" and seen["track"]["url"] == "u"


def test_download_subtitle_still_reports_login_when_no_tracks(monkeypatch, tmp_path):
    locked_info(monkeypatch, {})
    with pytest.raises(NoSubtitles, match="登录"):
        downloader.download_subtitle("https://www.bilibili.com/video/BV1", tmp_path)
