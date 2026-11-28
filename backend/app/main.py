import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import account_store, admin_store, ai, asr, config, downloader, guest, seo, tasks, transcription_auth, membership, payments, usage
from .account_auth import require_user, current_user
from .errors import AccountError, EmptySubtitles, NoSubtitles, TranscriptionError
from .transcriptions import TranscriptionManager, read_subtitles, result_payload
from .downloader import VideoError
from .jobs import JobManager
from .subtitles import to_plain_text
from .batch_transcriptions import BatchTranscriptionManager
from .guest_ai_trial import TrialManager

logging.basicConfig(level=logging.INFO)
# HTTP client INFO logs include signed result URLs. Never expose these in ordinary logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
manager = JobManager()
transcription_manager = TranscriptionManager()
batch_transcription_manager = BatchTranscriptionManager(lambda: transcription_manager)
payment_reconciler = payments.Reconciler()
guest_ai_manager = TrialManager(lambda: transcription_manager)


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        account_store.init_schema()
        admin_store.init_schema()
        membership.seed()
    except AccountError:
        logging.warning("Account database unavailable; guest features keep working, account APIs return 503")
    if config.ZPAY_MOCK and config.SESSION_SECURE:
        logging.error("ZPAY_MOCK is ignored because SESSION_SECURE=true (production)")
    elif config.ZPAY_MOCK:
        logging.warning("ZPAY_MOCK=true: payments use the local fake cashier, no real money is collected")
    manager.start_cleaner()
    transcription_manager.start()
    try:
        guest_ai_manager.start()
    except (AccountError, TranscriptionError):
        logging.warning('Guest AI trial recovery unavailable; new trial requests will retry database access')
    try:
        from .open_api_store import recover as recover_api_requests
        recover_api_requests()
    except AccountError:
        logging.warning('Open API request recovery unavailable; database access will be retried on restart')
    batch_transcription_manager.stopping.clear()
    payment_reconciler.start()
    yield
    payment_reconciler.stop()
    guest_ai_manager.stop()
    batch_transcription_manager.stopping.set()
    transcription_manager.stop()


app = FastAPI(title="FreeVideo 万能视频下载", lifespan=lifespan)


@app.exception_handler(AccountError)
async def account_error(_: Request, exc: AccountError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": exc.code},
                        headers={"Cache-Control": "no-store"})


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


class BatchTranscriptionReq(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=200)
    allow_asr: Literal[True]


def batch_cap(user_id):
    """(links allowed per batch for the user's plan, plan name); the global MAX_BATCH stays a hard ceiling."""
    plan = membership.limits(user_id)
    if not plan:
        return config.MAX_BATCH, None
    return min(plan['batch_max_links'], config.MAX_BATCH), plan['name']


def batch_limit_message(name, cap, count=None):
    seen = f'，当前 {count} 条' if count else ''
    return f'{name}单次最多批量处理 {cap} 条链接{seen}，可在定价页升级会员提高上限'


@app.post('/api/batch-transcriptions', dependencies=[Depends(require_user)])
def create_batch_transcription(req: BatchTranscriptionReq, request: Request, response: Response, user: dict = Depends(require_user)):
    transcription_auth.check_origin(request)
    owner = f"user:{user['id']}"
    transcription_auth.rate_limit(request, owner)
    response.headers['Cache-Control'] = 'no-store'
    cap, name = batch_cap(user['id'])
    return batch_transcription_manager.submit(owner, req.urls, cap, name)


@app.get('/api/batch-transcriptions/{job_id}', dependencies=[Depends(require_user)])
def batch_transcription_status(job_id: str, request: Request, response: Response, user: dict = Depends(require_user)):
    transcription_auth.check_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    job = batch_transcription_manager.get(job_id, f"user:{user['id']}")
    return batch_transcription_manager.public(job)


@app.get('/api/batch-transcriptions/{job_id}/file', dependencies=[Depends(require_user)])
def batch_transcription_archive(job_id: str, request: Request, user: dict = Depends(require_user)):
    transcription_auth.check_origin(request)
    content = batch_transcription_manager.archive(job_id, f"user:{user['id']}")
    return Response(content, media_type='application/zip', headers={
        'Content-Disposition': 'attachment; filename="FreeVideo-subtitles.zip"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


def _bad_request(e: Exception):
    raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
def health():
    return {"ok": True, "ai_enabled": ai.enabled(), "max_batch": config.MAX_BATCH,
            "asr_enabled": asr.enabled(), "asr_ready": asr.enabled() and transcription_manager.recovery_ready,
            "asr_max_minutes": config.ASR_MAX_DURATION // 60}


@app.post("/api/parse")
def parse(req: UrlReq, request: Request, response: Response, user: dict | None = Depends(current_user)):
    try:
        raw = None if user else guest.begin(request, req.url)
        info = downloader.parse(req.url)
        if raw:
            guest.record(request, response, raw, info)
        return info
    except VideoError as e:
        _bad_request(e)


@app.post("/api/download")
def download(req: DownloadReq, request: Request, user: dict | None = Depends(current_user)):
    try:
        url = downloader.extract_url(req.url)
        if not user:
            guest.require_known(request, url)
    except VideoError as e:
        _bad_request(e)
    return manager.submit(req.kind, tasks.single_download(url, req.quality, req.kind)).to_dict()


@app.post("/api/batch", dependencies=[Depends(require_user)])
def batch(req: BatchReq, user: dict = Depends(require_user)):
    urls = tasks.dedupe_urls(req.urls)
    if not urls:
        raise HTTPException(400, "未识别到有效链接")
    cap, name = batch_cap(user['id'])
    if len(urls) > cap:
        if name:
            raise AccountError('BATCH_LIMIT', batch_limit_message(name, cap, len(urls)), 403)
        raise HTTPException(400, f"单次最多批量下载 {config.MAX_BATCH} 个链接")
    return manager.submit("batch", tasks.batch_download(urls, req.quality, req.kind), title=f"批量下载 {len(urls)} 个").to_dict()


@app.post("/api/subtitles")
def subtitles(req: SubtitleReq, request: Request, user: dict | None = Depends(current_user)):
    try:
        url = downloader.extract_url(req.url)
        if not user:
            guest.require_known(request, url)
    except VideoError as e:
        _bad_request(e)
    return manager.submit("subtitle", tasks.subtitle_download(url, req.lang)).to_dict()


@app.post("/api/transcript")
def transcript(req: SubtitleReq, request: Request, user: dict | None = Depends(current_user)):
    try:
        url = downloader.extract_url(req.url)
        if not user:
            guest.require_known(request, url)
        config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=config.DOWNLOAD_DIR) as tmp:
            info, cues, metadata = read_subtitles(url, Path(tmp), req.lang)
        result = result_payload(cues, **metadata)
        if user:
            # Native subtitles are still free even if the history database temporarily fails.
            try:
                transcription_manager.save_native(user['id'], url, req.lang, info, result)
            except AccountError:
                logging.warning('Native subtitle history unavailable; returned the free transcript')
        return result
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
def create_transcription(req: TranscriptionReq, request: Request, response: Response, user: dict | None = Depends(current_user)):
    transcription_auth.check_origin(request)
    owner = f"user:{user['id']}" if user else transcription_auth.owner(request, response)
    transcription_auth.rate_limit(request, owner)
    response.headers["Cache-Control"] = "no-store"
    try:
        if not user:
            guest.require_known(request, req.url)
        max_dur = None if user else min(8 * 60, config.ASR_MAX_DURATION)
        return transcription_manager.submit(owner, req.url, req.lang, req.allow_asr, max_duration=max_dur).public()
    except TranscriptionError:
        raise
    except VideoError as e:
        _bad_request(e)


@app.get("/api/transcriptions/{job_id}")
def transcription_status(job_id: str, request: Request, response: Response, user: dict | None = Depends(current_user)):
    transcription_auth.check_origin(request)
    response.headers["Cache-Control"] = "no-store"
    owner = f"user:{user['id']}" if user else transcription_auth.owner(request)
    return transcription_manager.get(job_id, owner).public()


@app.get("/api/transcriptions/{job_id}/file")
def transcription_file(job_id: str, request: Request, format: Literal["txt", "srt"] = "txt", user: dict | None = Depends(current_user)):
    transcription_auth.check_origin(request)
    owner = f"user:{user['id']}" if user else transcription_auth.owner(request)
    job = transcription_manager.get(job_id, owner)
    if user and job.status == 'done' and job.result:
        from urllib.parse import quote
        content = job.result['srt' if format == 'srt' else 'text']
        return Response(content, media_type='text/plain; charset=utf-8', headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(job.title + '.' + format, safe='')})
    path = job.directory / f"transcript.{format}"
    if job.status != "done" or not path.is_file():
        raise TranscriptionError("NOT_FOUND", "文稿尚未生成或已过期", status=404)
    return FileResponse(path, filename=f"{job.title}.{format}",
                        media_type="text/plain" if format == "txt" else "application/x-subrip",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.post("/api/ai/translate", dependencies=[Depends(require_user)])
def translate(req: TranslateReq, user: dict = Depends(require_user)):
    if not ai.enabled():
        raise HTTPException(503, "AI 功能未启用：请在 backend/.env 中配置 DEEPSEEK_API_KEY")
    try:
        url = downloader.extract_url(req.url)
    except VideoError as e:
        _bad_request(e)
    ticket = usage.ai_begin(user['id'], url)
    inner = tasks.translate_subtitle(url, req.target_lang)

    def run(job):
        try:
            result = inner(job)
            usage.ai_commit(ticket)
            return result
        except BaseException:
            usage.ai_release(ticket)
            raise
    try:
        return manager.submit("translate", run).to_dict()
    except BaseException:
        usage.ai_release(ticket)
        raise


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/ai/summary", dependencies=[Depends(require_user)])
def summary(req: UrlReq, user: dict = Depends(require_user)):
    if not ai.enabled():
        raise HTTPException(503, "AI 功能未启用：请在 backend/.env 中配置 DEEPSEEK_API_KEY")
    ticket = usage.ai_begin(user['id'], req.url)

    def events():
        produced = False
        try:
            yield _sse("status", "正在获取视频字幕…")
            with tempfile.TemporaryDirectory(dir=config.DOWNLOAD_DIR) as tmp:
                info, cues = tasks.fetch_transcript(req.url, Path(tmp))
            yield _sse("meta", {"title": info.get("title"), "thumbnail": info.get("thumbnail"), "cues": len(cues)})
            yield _sse("status", "AI 正在总结…")
            for delta in ai.summarize_stream(info.get("title") or "", to_plain_text(cues)):
                produced = True
                yield _sse("delta", delta)
            yield _sse("done", True)
        except (VideoError, ai.AIDisabled) as e:
            yield _sse("error", str(e))
        except Exception as e:  # noqa: BLE001
            logging.exception("summary failed")
            yield _sse("error", f"AI 总结失败：{e}"[:200])
        finally:
            if produced:
                usage.ai_commit(ticket)
            else:
                usage.ai_release(ticket)

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
from .account_api import router as account_router  # noqa: E402
from .admin_api import router as admin_router  # noqa: E402
app.include_router(learning_router, dependencies=[Depends(require_user)])
app.include_router(account_router)
app.include_router(admin_router)
from .membership_api import router as membership_router  # noqa: E402
app.include_router(membership_router)
from .payment_api import router as payment_router  # noqa: E402
from .zpay_mock import router as zpay_mock_router  # noqa: E402
app.include_router(payment_router)
app.include_router(zpay_mock_router)  # every endpoint 404s unless ZPAY_MOCK=true outside production

from .open_api_api import create_router, account_router as api_keys_router, public_schema  # noqa: E402
open_router = create_router(lambda: transcription_manager)
app.include_router(open_router)
app.include_router(api_keys_router)
from .guest_ai_api import create_router as create_guest_ai_router  # noqa: E402
app.include_router(create_guest_ai_router(lambda: guest_ai_manager))


@app.get('/api/openapi.json', include_in_schema=False)
def open_api_schema():
    return JSONResponse(public_schema(open_router), headers={'Cache-Control': 'no-store'})


@app.get('/robots.txt', include_in_schema=False)
def robots_txt(request: Request):
    return PlainTextResponse(seo.render_robots_txt(seo.resolve_base_url(request)))


@app.get('/sitemap.xml', include_in_schema=False)
def sitemap_xml(request: Request):
    return Response(seo.render_sitemap_xml(seo.resolve_base_url(request)), media_type='application/xml; charset=utf-8')


@app.get('/llms.txt', include_in_schema=False)
def llms_txt(request: Request):
    return PlainTextResponse(seo.render_llms_txt(seo.resolve_base_url(request)))


@app.get('/llms-full.txt', include_in_schema=False)
def llms_full_txt(request: Request):
    return PlainTextResponse(seo.render_llms_full_txt(seo.resolve_base_url(request)))


if config.FRONTEND_DIST.exists():
    dist = config.FRONTEND_DIST.resolve()
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (dist / path).resolve()
        if path and f.is_file() and f.is_relative_to(dist):
            return FileResponse(f)
        template = (dist / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(seo.render_spa_html(template, path, seo.resolve_base_url(request)))
