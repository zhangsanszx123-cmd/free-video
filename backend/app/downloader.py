"""Thin wrapper around yt-dlp's Python API."""
import re
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError

from . import config, douyin
from .errors import VideoError

URL_RE = re.compile(r"https?://[^\s<>\"'，。！？、；）)】\]]+")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SUB_PREFERENCE = ["zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "ai-zh", "en", "en-US", "en-orig", "ja", "ko"]
IGNORED_SUBS = {"danmaku", "live_chat", "comments"}
NO_DIRECT_EXTRACTORS = {"Youtube"}  # googlevideo links are bound to the server IP

Report = Callable[..., None]


def extract_url(text: str) -> str:
    m = URL_RE.search(text or "")
    if not m:
        raise VideoError("未识别到有效链接，请粘贴以 http(s):// 开头的视频分享链接")
    return m.group(0)


def friendly_error(err: Exception) -> str:
    msg = ANSI_RE.sub("", str(err)).replace("ERROR: ", "").strip()
    low = msg.lower()
    rules = [
        ("unsupported url", "暂不支持该链接，请确认是视频详情页/分享链接"),
        ("cookies", "该平台需要登录才能下载（本站不使用账号 Cookie，仅支持公开内容）"),
        ("login", "该内容需要登录才能访问，仅支持公开视频"),
        ("private", "该视频为私密内容，无法下载"),
        ("geo", "该视频存在地区限制，服务器所在地区无法访问"),
        ("not available", "视频不存在或已被删除"),
        ("timed out", "网络超时，请稍后重试（海外平台可能需要配置代理）"),
        ("unable to download webpage", "无法访问该网页，请检查链接或稍后重试"),
        ("please report this issue", "视频不存在、链接无效，或平台接口发生变化，请检查链接后重试"),
    ]
    for key, text in rules:
        if key in low:
            return text
    return "解析失败：" + msg[:200]


def base_opts(**extra) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 3,
        "windowsfilenames": True,
    }
    if config.YTDLP_PROXY:
        opts["proxy"] = config.YTDLP_PROXY
    opts.update(extra)
    return opts


def _first_entry(info: dict) -> dict:
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise VideoError("该链接中没有可下载的视频")
        return entries[0]
    return info


def extract_info(text: str, **opts) -> dict:
    url = extract_url(text)
    try:
        with YoutubeDL(base_opts(skip_download=True, **opts)) as ydl:
            return _first_entry(ydl.extract_info(url, download=False))
    except (DownloadError, ExtractorError) as e:
        raise VideoError(friendly_error(e)) from e


def _has(f: dict, key: str) -> bool:
    return f.get(key) not in ("none",)


def _quality_label(h: int) -> str:
    return {4320: "8K", 2160: "4K", 1440: "2K"}.get(h, f"{h}P")


def _estimate_size(formats: list, height: int, duration) -> int | None:
    best = None
    for f in formats:
        if f.get("height") == height and _has(f, "vcodec"):
            size = f.get("filesize") or f.get("filesize_approx")
            if not size and f.get("tbr") and duration:
                size = f["tbr"] * 125 * duration
            if size and (best is None or size > best):
                best = size
    return int(best) if best else None


def _pick_direct(info: dict, formats: list) -> dict | None:
    if info.get("extractor_key") in NO_DIRECT_EXTRACTORS:
        return None
    candidates = []
    for f in formats:
        headers = {k.lower() for k in (f.get("http_headers") or {})}
        if (
            f.get("url")
            and f.get("protocol") in ("http", "https")
            and f.get("ext") == "mp4"
            and _has(f, "vcodec")
            and _has(f, "acodec")
            and not f.get("cookies")
            and not headers & {"referer", "cookie"}
        ):
            candidates.append(f)
    if not candidates:
        return None
    f = max(candidates, key=lambda x: (x.get("height") or 0, x.get("tbr") or 0))
    return {"url": f["url"], "height": f.get("height"), "ext": f["ext"]}


def list_subtitles(info: dict) -> list[dict]:
    result = [
        {"lang": k, "name": (v[0].get("name") if v else None) or k, "auto": False}
        for k, v in (info.get("subtitles") or {}).items()
        if k not in IGNORED_SUBS
    ]
    have = {s["lang"] for s in result}
    for k, v in (info.get("automatic_captions") or {}).items():
        if k not in have and (k in SUB_PREFERENCE or k.endswith("-orig")):
            result.append({"lang": k, "name": ((v[0].get("name") if v else None) or k) + "（自动）", "auto": True})
    return result


def choose_subtitle(info: dict) -> str | None:
    subs = list_subtitles(info)
    for auto in (False, True):
        group = [s["lang"] for s in subs if s["auto"] == auto]
        for lang in SUB_PREFERENCE:
            if lang in group:
                return lang
        if group:
            return group[0]
    return None


def summarize(info: dict) -> dict:
    formats = info.get("formats") or [info]
    duration = info.get("duration")
    heights = sorted({f["height"] for f in formats if f.get("height") and _has(f, "vcodec")}, reverse=True)
    return {
        "url": info.get("webpage_url") or info.get("original_url"),
        "id": info.get("id"),
        "title": info.get("title") or "未命名视频",
        "thumbnail": info.get("thumbnail"),
        "duration": duration,
        "uploader": info.get("uploader") or info.get("channel"),
        "platform": info.get("extractor_key") or info.get("extractor"),
        "view_count": info.get("view_count"),
        "qualities": [
            {"height": h, "label": _quality_label(h), "size": _estimate_size(formats, h, duration), "pro": h >= 1080}
            for h in heights
        ],
        "has_audio": not all(f.get("acodec") == "none" for f in formats),
        "subtitles": list_subtitles(info),
        "direct": _pick_direct(info, formats),
    }


def parse(text: str) -> dict:
    url = extract_url(text)
    if douyin.is_douyin(url):
        return douyin.parse(url)
    return summarize(extract_info(url))


def _collect_files(outdir: Path, suffixes: tuple[str, ...] | None = None) -> list[Path]:
    files = [
        p for p in outdir.iterdir()
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp")) and ".part-Frag" not in p.name
    ]
    if suffixes:
        files = [p for p in files if p.suffix.lower() in suffixes]
    return sorted(files, key=lambda p: p.stat().st_size, reverse=True)


def download(text: str, outdir: Path, quality: int | None = None, kind: str = "video", report: Report = lambda **_: None) -> Path:
    """Download a single video/audio into outdir and return the final file path."""
    url = extract_url(text)
    if douyin.is_douyin(url):
        return douyin.download(url, outdir, kind, report)
    outdir.mkdir(parents=True, exist_ok=True)
    state = {"finished": 0, "stages": 1}

    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = (d.get("downloaded_bytes") or 0) / total * 100 if total else 0
            overall = (state["finished"] * 100 + pct) / state["stages"]
            report(status="running", progress=round(min(overall, 99), 1), speed=d.get("speed"), eta=d.get("eta"))
        elif d["status"] == "finished":
            state["finished"] += 1

    def pp_hook(d):
        if d["status"] == "started" and d.get("postprocessor") in ("Merger", "ExtractAudio", "FFmpegVideoRemuxer"):
            report(status="processing", message="正在合并/转码，请稍候…")

    opts = base_opts(
        outtmpl=str(outdir / "%(title).80B [%(id)s].%(ext)s"),
        progress_hooks=[progress_hook],
        postprocessor_hooks=[pp_hook],
        max_filesize=config.MAX_FILESIZE_MB * 1024 * 1024,
        concurrent_fragment_downloads=4,
    )
    if kind == "audio":
        opts.update(format="ba/b", postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}])
    else:
        h = f"[height<={int(quality)}]" if quality else ""
        opts.update(
            format=f"bv*{h}+ba/b{h}/bv*+ba/b",
            format_sort=["res", "vcodec:h264", "ext:mp4:m4a"],
            merge_output_format="mp4",
        )
    try:
        with YoutubeDL(opts) as ydl:
            info = _first_entry(ydl.extract_info(url, download=False))
            state["stages"] = len(info.get("requested_formats") or [None])
            report(title=info.get("title"), thumbnail=info.get("thumbnail"))
            ydl.process_ie_result(info, download=True)
    except (DownloadError, ExtractorError) as e:
        raise VideoError(friendly_error(e)) from e
    files = _collect_files(outdir, (".mp3",) if kind == "audio" else None)
    if not files:
        raise VideoError(f"下载失败：文件可能超过 {config.MAX_FILESIZE_MB}MB 上限或格式不可用")
    return files[0]


def download_subtitle(text: str, outdir: Path, lang: str | None = None) -> tuple[Path, dict]:
    """Download one subtitle track as SRT. Returns (path, info)."""
    if douyin.is_douyin(extract_url(text)):
        raise VideoError("抖音作品没有字幕，暂不支持字幕下载与 AI 总结")
    info = extract_info(text)
    lang = lang or choose_subtitle(info)
    if not lang:
        raise VideoError("该视频没有可用字幕")
    outdir.mkdir(parents=True, exist_ok=True)
    opts = base_opts(
        skip_download=True,
        writesubtitles=True,
        writeautomaticsub=True,
        subtitleslangs=[lang],
        subtitlesformat="srt/vtt/best",
        outtmpl=str(outdir / "%(title).80B [%(id)s].%(ext)s"),
        postprocessors=[{"key": "FFmpegSubtitlesConvertor", "format": "srt"}],
    )
    try:
        with YoutubeDL(opts) as ydl:
            ydl.process_ie_result(info, download=True)
    except (DownloadError, ExtractorError) as e:
        raise VideoError(friendly_error(e)) from e
    files = _collect_files(outdir, (".srt",))
    if not files:
        raise VideoError(f"字幕（{lang}）下载失败或不存在")
    return files[0], info
