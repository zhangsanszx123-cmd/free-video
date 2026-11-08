"""Anonymous Bilibili subtitle fallback.

yt-dlp reads subtitles from the player API, which answers `need_login_subtitle` without an
account. The danmaku view endpoint still returns signed subtitle URLs anonymously, so when
yt-dlp reports a login requirement we use it. No cookies or accounts are involved.
"""
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .errors import VideoError
from .subtitles import Cue, timestamp_from_ms, to_srt

VIEW_API = "https://api.bilibili.com/x/web-interface/view"
DM_VIEW_API = "https://api.bilibili.com/x/v2/dm/view"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}
TRUSTED_HOST = "hdslb.com"
PART_RE = re.compile(r"_p(\d+)$")
SAFE_NAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
log = logging.getLogger("freevideo.bilibili_subs")


def _get(url: str, **kw) -> httpx.Response:
    r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=False, **kw)
    r.raise_for_status()
    return r


def _normalize(url: str) -> str | None:
    if url.startswith("//"):
        url = "https:" + url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not (host == TRUSTED_HOST or host.endswith("." + TRUSTED_HOST)):
        return None
    return "https" + url[len(p.scheme):]


def tracks(info: dict) -> dict[str, dict]:
    """Return {lang: {name, auto, url}} for the original-language tracks; {} on any failure."""
    if info.get("extractor_key") != "BiliBili":
        return {}
    try:
        video_id = str(info.get("id") or "")
        bvid = PART_RE.sub("", video_id)
        view = _get(VIEW_API, params={"bvid": bvid}).json()
        data = view["data"]
        part = int(m.group(1)) if (m := PART_RE.search(video_id)) else 1
        cid = next(p["cid"] for p in data["pages"] if p["page"] == part)
        dm = _get(DM_VIEW_API, params={"type": 1, "oid": cid, "pid": data["aid"]}).json()
        if dm.get("code") != 0:
            return {}
        result: dict[str, dict] = {}
        for t in dm["data"]["subtitle"]["subtitles"]:
            url = _normalize(t.get("subtitle_url") or "")
            if not url or not t.get("lan") or t.get("ai_type"):
                continue  # skip empty URLs and machine translations of the original track
            result[t["lan"]] = {"name": t.get("lan_doc") or t["lan"], "auto": bool(t.get("type")), "url": url}
        return result
    except (httpx.HTTPError, KeyError, StopIteration, TypeError, ValueError) as e:
        log.warning("bilibili subtitle fallback failed: %s", type(e).__name__)
        return {}


def to_srt_text(body: list[dict]) -> str:
    cues = [
        Cue(timestamp_from_ms(round(float(b["from"]) * 1000)), timestamp_from_ms(round(float(b["to"]) * 1000)), text)
        for b in body if (text := " ".join(str(b.get("content") or "").split()))
    ]
    return to_srt(cues)


def download(track: dict, outdir: Path, info: dict, lang: str) -> Path:
    try:
        body = _get(track["url"]).json().get("body") or []
        srt = to_srt_text(body)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        raise VideoError("字幕下载失败，请稍后重试") from e
    if not srt:
        raise VideoError(f"字幕（{lang}）内容为空")
    outdir.mkdir(parents=True, exist_ok=True)
    name = SAFE_NAME_RE.sub("_", info.get("title") or "subtitle")[:80].strip()
    path = outdir / f"{name} [{info.get('id')}].{lang}.srt"
    path.write_text(srt, encoding="utf-8", newline="\n")
    return path
