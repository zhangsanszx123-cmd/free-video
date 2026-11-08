import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, asr, config, downloader, tasks, transcription_auth
from .errors import EmptySubtitles, NoSubtitles, TranscriptionError
from .transcriptions import TranscriptionManager, read_subtitles, result_payload
from .downloader import VideoError
from .jobs import JobManager
from .subtitles import to_plain_text

logging.basicConfig(level=logging.INFO)
# HTTP client INFO logs include signed result URLs. Never expose these in ordinary logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
manager = JobManager()
transcription_manager = TranscriptionManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    manager.start_cleaner()
    transcription_manager.start()
    yield
    transcription_manager.stop()


app = FastAPI(title="FreeVideo 万能视频下载", lifespan=lifespan)


@app.exception_handler(TranscriptionError)
async def transcription_error(_: Request, exc: TranscriptionError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": exc.code, "retryable": exc.retryable},
                        headers={"Cache-Control": "no-store"})


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


class TranscriptionReq(SubtitleReq):
    allow_asr: bool = False


def _bad_request(e: Exception):
    raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
def health():
    return {"ok": True, "ai_enabled": ai.enabled(), "max_batch": config.MAX_BATCH,
            "asr_enabled": asr.enabled(), "asr_ready": asr.enabled() and transcription_manager.recovery_ready,
            "asr_max_minutes": config.ASR_MAX_DURATION // 60}


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
        config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=config.DOWNLOAD_DIR) as tmp:
            _, cues, metadata = read_subtitles(url, Path(tmp), req.lang)
        return result_payload(cues, **metadata)
    except NoSubtitles as e:
        raise TranscriptionError("NO_SUBTITLES", str(e), True) from e
    except EmptySubtitles as e:
        raise TranscriptionError("EMPTY_SUBTITLES", str(e), True) from e
    except VideoError as e:
        _bad_request(e)


@app.get("/api/transcription-session")
def transcription_session(request: Request, response: Response):
    transcription_auth.check_origin(request)
    transcription_auth.owner(request, response)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@app.post("/api/transcriptions")
def create_transcription(req: TranscriptionReq, request: Request, response: Response):
    transcription_auth.check_origin(request)
    owner = transcription_auth.owner(request, response)
    transcription_auth.rate_limit(request, owner)
    response.headers["Cache-Control"] = "no-store"
    try:
        return transcription_manager.submit(owner, req.url, req.lang, req.allow_asr).public()
    except TranscriptionError:
        raise
    except VideoError as e:
        _bad_request(e)


@app.get("/api/transcriptions/{job_id}")
def transcription_status(job_id: str, request: Request, response: Response):
    transcription_auth.check_origin(request)
    response.headers["Cache-Control"] = "no-store"
    return transcription_manager.get(job_id, transcription_auth.owner(request)).public()


@app.get("/api/transcriptions/{job_id}/file")
def transcription_file(job_id: str, request: Request, format: Literal["txt", "srt"] = "txt"):
    transcription_auth.check_origin(request)
    job = transcription_manager.get(job_id, transcription_auth.owner(request))
    path = job.directory / f"transcript.{format}"
    if job.status != "done" or not path.is_file():
        raise TranscriptionError("NOT_FOUND", "文稿尚未生成或已过期", status=404)
    return FileResponse(path, filename=f"{job.title}.{format}",
                        media_type="text/plain" if format == "txt" else "application/x-subrip",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


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


from .ai_learning_api import router as learning_router  # noqa: E402
app.include_router(learning_router)


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
