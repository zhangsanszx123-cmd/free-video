import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, config, downloader, tasks
from .downloader import VideoError
from .jobs import JobManager
from .subtitles import parse_srt, to_plain_text

logging.basicConfig(level=logging.INFO)
manager = JobManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    manager.start_cleaner()
    yield


app = FastAPI(title="FreeVideo 万能视频下载", lifespan=lifespan)


class UrlReq(BaseModel):
    url: str = Field(max_length=2000)


class DownloadReq(UrlReq):
    quality: int | None = None
    kind: Literal["video", "audio"] = "video"


class BatchReq(BaseModel):
    urls: list[str] = Field(max_length=200)
    quality: int | None = None
    kind: Literal["video", "audio"] = "video"


class SubtitleReq(UrlReq):
    lang: str | None = None


class TranslateReq(UrlReq):
    target_lang: str = "简体中文"


def _bad_request(e: Exception):
    raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
def health():
    return {"ok": True, "ai_enabled": ai.enabled(), "max_batch": config.MAX_BATCH}


@app.post("/api/parse")
def parse(req: UrlReq):
    try:
        return downloader.parse(req.url)
    except VideoError as e:
        _bad_request(e)


@app.post("/api/download")
def download(req: DownloadReq):
    try:
        url = downloader.extract_url(req.url)
    except VideoError as e:
        _bad_request(e)
    return manager.submit(req.kind, tasks.single_download(url, req.quality, req.kind)).to_dict()


@app.post("/api/batch")
def batch(req: BatchReq):
    urls = tasks.dedupe_urls(req.urls)
    if not urls:
        raise HTTPException(400, "未识别到有效链接")
    if len(urls) > config.MAX_BATCH:
        raise HTTPException(400, f"单次最多批量下载 {config.MAX_BATCH} 个链接")
    return manager.submit("batch", tasks.batch_download(urls, req.quality, req.kind), title=f"批量下载 {len(urls)} 个").to_dict()


@app.post("/api/subtitles")
def subtitles(req: SubtitleReq):
    try:
        url = downloader.extract_url(req.url)
    except VideoError as e:
        _bad_request(e)
    return manager.submit("subtitle", tasks.subtitle_download(url, req.lang)).to_dict()


@app.post("/api/transcript")
def transcript(req: SubtitleReq):
    try:
        url = downloader.extract_url(req.url)
        with tempfile.TemporaryDirectory(dir=config.DOWNLOAD_DIR) as tmp:
            path, _ = downloader.download_subtitle(url, Path(tmp), req.lang)
            cues = parse_srt(path.read_text(encoding="utf-8", errors="ignore"))
        if not cues:
            raise VideoError("字幕内容为空")
        return {
            "text": " ".join(c.text for c in cues),
            "timed_text": to_plain_text(cues, with_time=True),
            "cues": len(cues),
        }
    except VideoError as e:
        _bad_request(e)


@app.post("/api/ai/translate")
def translate(req: TranslateReq):
    if not ai.enabled():
        raise HTTPException(503, "AI 功能未启用：请在 backend/.env 中配置 DEEPSEEK_API_KEY")
    try:
        url = downloader.extract_url(req.url)
    except VideoError as e:
        _bad_request(e)
    return manager.submit("translate", tasks.translate_subtitle(url, req.target_lang)).to_dict()


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/ai/summary")
def summary(req: UrlReq):
    if not ai.enabled():
        raise HTTPException(503, "AI 功能未启用：请在 backend/.env 中配置 DEEPSEEK_API_KEY")

    def events():
        try:
            yield _sse("status", "正在获取视频字幕…")
            with tempfile.TemporaryDirectory(dir=config.DOWNLOAD_DIR) as tmp:
                info, cues = tasks.fetch_transcript(req.url, Path(tmp))
            yield _sse("meta", {"title": info.get("title"), "thumbnail": info.get("thumbnail"), "cues": len(cues)})
            yield _sse("status", "AI 正在总结…")
            for delta in ai.summarize_stream(info.get("title") or "", to_plain_text(cues)):
                yield _sse("delta", delta)
            yield _sse("done", True)
        except (VideoError, ai.AIDisabled) as e:
            yield _sse("error", str(e))
        except Exception as e:  # noqa: BLE001
            logging.exception("summary failed")
            yield _sse("error", f"AI 总结失败：{e}"[:200])

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在或已过期")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str):
    job = manager.get(job_id)
    if not job or not job.filepath or not job.filepath.exists():
        raise HTTPException(404, "文件不存在或已过期（文件保留 30 分钟）")
    return FileResponse(job.filepath, filename=job.filepath.name)


if config.FRONTEND_DIST.exists():
    dist = config.FRONTEND_DIST.resolve()
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (dist / path).resolve()
        if path and f.is_file() and f.is_relative_to(dist):
            return FileResponse(f)
        return FileResponse(dist / "index.html")
