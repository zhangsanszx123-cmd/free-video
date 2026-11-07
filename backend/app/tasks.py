"""Job bodies executed by JobManager workers."""
import re
import zipfile
from pathlib import Path

from . import ai, downloader
from .downloader import VideoError
from .jobs import Job
from .subtitles import parse_srt, to_srt


def single_download(url: str, quality: int | None, kind: str):
    def run(job: Job) -> Path:
        return downloader.download(url, job.dir, quality, kind, report=job.update)
    return run


def dedupe_urls(texts: list[str]) -> list[str]:
    urls, seen = [], set()
    for t in texts:
        for m in downloader.URL_RE.finditer(t or ""):
            if m.group(0) not in seen:
                seen.add(m.group(0))
                urls.append(m.group(0))
    return urls


def batch_download(urls: list[str], quality: int | None, kind: str):
    def run(job: Job) -> Path:
        job.items = [{"url": u, "status": "queued", "title": None, "progress": 0, "error": None} for u in urls]
        files: list[Path] = []
        for i, item in enumerate(job.items):
            def report(**f):
                item.update({k: v for k, v in f.items() if k in ("status", "title", "progress")})
                job.update(progress=round((i * 100 + item["progress"]) / len(urls), 1), message=f"正在下载第 {i + 1}/{len(urls)} 个")
            item["status"] = "running"
            try:
                files.append(downloader.download(item["url"], job.dir / f"{i + 1:02d}", quality, kind, report=report))
                item.update(status="done", progress=100)
            except VideoError as e:
                item.update(status="error", error=str(e))
        if not files:
            raise VideoError("全部链接下载失败，请检查链接是否有效")
        job.update(status="processing", message="正在打包 ZIP…")
        zip_path = job.dir / f"FreeVideo批量下载_{len(files)}个.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for f in files:
                zf.write(f, f"{f.parent.name}_{f.name}")
        return zip_path
    return run


def subtitle_download(url: str, lang: str | None):
    def run(job: Job) -> Path:
        path, info = downloader.download_subtitle(url, job.dir, lang)
        job.update(title=info.get("title"))
        return path
    return run


def fetch_transcript(url: str, workdir: Path) -> tuple[dict, list]:
    path, info = downloader.download_subtitle(url, workdir)
    cues = parse_srt(path.read_text(encoding="utf-8", errors="ignore"))
    if not cues:
        raise VideoError("字幕内容为空，无法进行 AI 处理")
    return info, cues


def translate_subtitle(url: str, target_lang: str):
    def run(job: Job) -> Path:
        job.update(message="正在获取字幕…")
        info, cues = fetch_transcript(url, job.dir / "src")
        job.update(title=info.get("title"), message=f"AI 翻译中（共 {len(cues)} 条字幕）…")
        translations = ai.translate_cues(cues, target_lang, on_progress=lambda p: job.update(progress=round(p, 1)))
        safe = re.sub(r'[\\/:*?"<>|]', "_", info.get("title") or "subtitle")[:80]
        job.dir.mkdir(parents=True, exist_ok=True)
        out = job.dir / f"{safe}.双语.{target_lang}.srt"
        out.write_text(to_srt(cues, translations), encoding="utf-8", newline="\n")
        return out
    return run
