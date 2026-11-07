"""Douyin adapter built on Johnserf-Seed/f2.

yt-dlp's Douyin extractor needs signed browser cookies it cannot generate, so Douyin links are
routed here. f2 signs the web API (a_bogus) and we only supply an auto-generated guest cookie
(ttwid + msToken) - no account login is involved.
"""
import asyncio
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from . import config
from .errors import VideoError

HOSTS = ("douyin.com", "iesdouyin.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")
HEADERS = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
ID_PATTERNS = [re.compile(r"/(?:video|note)/(\d{8,})"), re.compile(r"modal_id=(\d{8,})")]
COOKIE_TTL = 20 * 60
SAFE_NAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')

_cookie = {"value": None, "at": 0.0}
_cookie_lock = threading.Lock()
log = logging.getLogger("freevideo.douyin")

Report = Callable[..., None]


def is_douyin(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def _guest_cookie(refresh: bool = False) -> str:
    from f2.apps.douyin.utils import TokenManager

    with _cookie_lock:
        if refresh or not _cookie["value"] or time.time() - _cookie["at"] > COOKIE_TTL:
            _cookie["value"] = f"ttwid={TokenManager.gen_ttwid()}; msToken={TokenManager.gen_real_msToken()};"
            _cookie["at"] = time.time()
        return _cookie["value"]


async def _fetch(url: str, cookie: str) -> dict:
    from f2.apps.douyin.handler import DouyinHandler
    from f2.apps.douyin.utils import AwemeIdFetcher

    logging.getLogger("f2").setLevel(logging.WARNING)
    aweme_id = next((m.group(1) for p in ID_PATTERNS if (m := p.search(url))), None)
    if not aweme_id:
        aweme_id = await AwemeIdFetcher.get_aweme_id(url)
    kwargs = {"headers": HEADERS, "proxies": {"http://": None, "https://": None}, "cookie": cookie, "timeout": 15}
    return (await DouyinHandler(kwargs).fetch_one_video(aweme_id))._to_dict()


def friendly_error(err: Exception) -> str:
    msg = str(err)
    if any(k in msg for k in ("删除", "无法观看", "私密", "权限")):
        return "抖音作品不存在、已删除或仅作者可见"
    if any(k in msg for k in ("不合法", "未在响应的地址中找到", "暂时不支持")):
        return "无法识别该抖音链接，请使用作品的分享链接"
    if "超时" in msg or "Timeout" in type(err).__name__:
        return "连接抖音超时，请稍后重试"
    return "抖音解析失败：平台接口可能已更新，请稍后重试"


def fetch_detail(url: str) -> dict:
    """Fetch aweme detail; retries once with a fresh guest cookie."""
    last: Exception | None = None
    for attempt in range(2):
        try:
            return asyncio.run(_fetch(url, _guest_cookie(refresh=attempt > 0)))
        except Exception as e:  # noqa: BLE001 - f2 raises many exception types
            last = e
            log.warning("douyin fetch failed (attempt %s): %s", attempt + 1, e)
            if friendly_error(e) != friendly_error(Exception()):
                break  # deterministic error, retry won't help
    raise VideoError(friendly_error(last)) from last


def _play_urls(d: dict) -> list[str]:
    plays = d.get("video_play_addr") or []
    if plays and isinstance(plays[0], list):
        plays = plays[0]
    return [u for u in plays if isinstance(u, str) and u.startswith("http")]


def summarize(d: dict, url: str) -> dict:
    if d.get("images"):
        raise VideoError("暂不支持抖音图文作品，目前仅支持视频")
    plays = _play_urls(d)
    if not plays:
        raise VideoError("未获取到抖音视频地址，请稍后重试")
    duration = d.get("duration")
    return {
        "url": f"https://www.douyin.com/video/{d.get('aweme_id')}" if d.get("aweme_id") else url,
        "id": d.get("aweme_id"),
        "title": (d.get("desc_raw") or d.get("desc") or "").strip() or f"抖音作品 {d.get('aweme_id')}",
        "thumbnail": d.get("cover"),
        "duration": duration / 1000 if duration else None,
        "uploader": d.get("nickname_raw") or d.get("nickname"),
        "platform": "Douyin",
        "view_count": None,
        "qualities": [],
        "has_audio": True,
        "subtitles": [],
        "direct": {"url": plays[0], "height": None, "ext": "mp4"},
    }


def parse(url: str) -> dict:
    return summarize(fetch_detail(url), url)


def _stream(urls: list[str], dest: Path, report: Report):
    limit = config.MAX_FILESIZE_MB * 1024 * 1024
    last: Exception | None = None
    for url in urls:
        try:
            with httpx.stream("GET", url, headers=HEADERS, follow_redirects=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                if total > limit:
                    raise VideoError(f"文件超过 {config.MAX_FILESIZE_MB}MB 上限")
                done, start = 0, time.time()
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(256 * 1024):
                        f.write(chunk)
                        done += len(chunk)
                        speed = done / max(time.time() - start, 1e-3)
                        report(status="running", progress=round(min(done / total * 100, 99), 1) if total else 0,
                               speed=speed, eta=int((total - done) / speed) if total else None)
            return
        except VideoError:
            raise
        except httpx.HTTPError as e:
            last = e
            log.warning("douyin stream failed: %s", e)
    raise VideoError("抖音视频下载失败，请稍后重试") from last


def download(url: str, outdir: Path, kind: str = "video", report: Report = lambda **_: None) -> Path:
    detail = fetch_detail(url)  # play urls expire quickly, so always fetch right before downloading
    info = summarize(detail, url)
    report(title=info["title"], thumbnail=info["thumbnail"])
    outdir.mkdir(parents=True, exist_ok=True)
    name = f"{SAFE_NAME_RE.sub('_', info['title'])[:80].strip()} [{info['id']}]"
    mp4 = outdir / f"{name}.mp4"
    _stream(_play_urls(detail), mp4, report)
    if kind != "audio":
        return mp4
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoError("服务器未安装 ffmpeg，无法转码 MP3")
    report(status="processing", message="正在转码 MP3，请稍候…")
    mp3 = mp4.with_suffix(".mp3")
    proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp4), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)],
                          capture_output=True)
    if proc.returncode != 0 or not mp3.exists():
        raise VideoError("MP3 转码失败")
    mp4.unlink(missing_ok=True)
    return mp3
