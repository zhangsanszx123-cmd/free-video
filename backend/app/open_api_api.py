"""Versioned developer API and website-only key management."""
import hashlib
import json
import logging
import re
import threading
import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from . import account_auth, membership, open_api_auth, open_api_store
from .errors import AccountError, TranscriptionError, VideoError

log = logging.getLogger('freevideo.open_api')
submission_lock = threading.RLock()  # single process; NEVER hold a SQL lock while waiting here


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorBody


class OpenRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            request.state.open_request_id = uuid.uuid4().hex
            try:
                response = await original(request)
            except (AccountError, TranscriptionError) as exc:
                response = JSONResponse(status_code=exc.status, content={
                    'request_id': request.state.open_request_id,
                    'error': {'code': exc.code, 'message': str(exc), 'retryable': getattr(exc, 'retryable', exc.status in (429, 503))}})
            except (RequestValidationError, VideoError):
                response = JSONResponse(status_code=422, content={'request_id': request.state.open_request_id,
                    'error': {'code': 'INVALID_REQUEST', 'message': '参数无效，请核对必填字段、类型和长度', 'retryable': False}})
            except Exception:
                # Do not log raw exceptions, credentials, submitted URLs or provider output.
                log.error('open API request %s failed', request.state.open_request_id)
                response = JSONResponse(status_code=503, content={'request_id': request.state.open_request_id,
                    'error': {'code': 'SERVICE_UNAVAILABLE', 'message': '服务暂不可用，请稍后查询原任务', 'retryable': True}})
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Request-ID'] = request.state.open_request_id
            if response.status_code == 429:
                response.headers['Retry-After'] = '60'
            if response.status_code == 401:
                response.headers['WWW-Authenticate'] = 'Bearer'
            return response
        return handle


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=1, max_length=2000)
    allow_asr: StrictBool = False
    lang: str | None = Field(default=None, min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')


class TranscriptResult(BaseModel):
    text: str
    timed_text: str
    srt: str
    cue_count: int
    source: Literal['platform_subtitle', 'automatic_subtitle', 'asr']
    language: str | None = None


class TaskData(BaseModel):
    task_id: str
    status: Literal['queued', 'running', 'succeeded', 'failed', 'uncertain']
    stage: str
    message: str
    title: str | None = None
    platform: str | None = None
    source_url: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    duration_seconds: float | None = None
    created_at: str
    expires_at: str
    result: TranscriptResult | None = None
    error: ErrorBody | None = None
    media_notice: str = '视频和封面为平台临时地址，可能过期或受防盗链限制；无法获取时为 null，不保证与任务保留期相同。'


class TaskResponse(BaseModel):
    request_id: str
    data: TaskData


class QuotaData(BaseModel):
    plan: str
    limit_seconds: int
    used_seconds: int
    reserved_seconds: int
    pending_previous_seconds: int
    available_seconds: int
    resets_at: str
    asr_max_minutes: int


class QuotaResponse(BaseModel):
    request_id: str
    data: QuotaData


def create_router(get_manager):
    router = APIRouter(prefix='/api/open/v1', tags=['开放 API'], route_class=OpenRoute,
                       responses={code: {'model': ErrorResponse} for code in (401, 403, 404, 409, 422, 429, 503)})

    def limited(principal, action):
        account_auth.rate_limit(f"open-{action}:{principal['user_id']}", 10 if action == 'submit' else 60, 60)

    def task(row):
        if not row:
            raise AccountError('NOT_FOUND', '任务不存在或已过期', 404)
        if row['failure']:
            return TaskData(task_id=row['id'], status='failed', stage='error', message=row['failure']['message'],
                            created_at=membership.iso(row['created_at']), expires_at=membership.iso(row['expires_at']), error=row['failure'])
        job = get_manager().get(row['transcription_id'], f"user:{row['user_id']}")
        saved = membership.record(row['user_id'], job_id=job.id)
        expires = min(row['expires_at'], saved['expires_at']) if saved else row['expires_at']
        state = ('uncertain' if job.error_code == 'SUBMISSION_UNCERTAIN' else
                 {'queued': 'queued', 'running': 'running', 'done': 'succeeded', 'error': 'failed'}.get(job.status, 'running'))
        media = job.media or {}
        result = None
        if state == 'succeeded' and job.result:
            result = {**job.result, 'cue_count': job.result['cues']}
        error = {'code': job.error_code or 'PROCESSING_FAILED', 'message': job.error or '处理失败', 'retryable': job.retryable} if state in ('failed', 'uncertain') else None
        return TaskData(task_id=row['id'], status=state, stage=job.stage, message=job.message, title=job.title,
                        **{k: media.get(k) for k in ('platform', 'source_url', 'video_url', 'cover_url', 'duration_seconds')},
                        created_at=membership.iso(row['created_at']), expires_at=membership.iso(expires), result=result, error=error)

    @router.post('/transcriptions', status_code=202, response_model=TaskResponse, summary='提交视频文案提取任务')
    def create(req: CreateRequest, request: Request, principal=Depends(open_api_auth.require_key)):
        limited(principal, 'submit')
        idem = request.headers.get('idempotency-key', '')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', idem):
            raise AccountError('INVALID_IDEMPOTENCY_KEY', '请提供 1–128 位字母、数字、下划线、点、冒号或连字符组成的 Idempotency-Key', 422)
        # Hash locally extracted input before resolving shortlinks so a timeout retry needs no network.
        from .downloader import extract_url
        normalized = {**req.model_dump(), 'url': extract_url(req.url)}
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with submission_lock:
            # No API admission can be in progress while this lock is held. Also
            # recover abandoned grants after a transient DB outage, without a restart.
            open_api_store.recover()
            row, fresh = open_api_store.admit(principal, idem, digest)
            if fresh:
                try:
                    url = open_api_auth.video_url(req.url)
                    get_manager().submit(f"user:{principal['user_id']}", url, req.lang, req.allow_asr,
                                         job_id=row['transcription_id'], on_accept=lambda job: open_api_store.bind(row, job))
                except (AccountError, TranscriptionError, VideoError) as exc:
                    open_api_store.fail(row, getattr(exc, 'code', 'VIDEO_FAILED'), str(exc), getattr(exc, 'retryable', False))
                    raise
                except Exception:
                    # submit's only work after successful enqueue is returning the job.
                    # Never automatically enqueue a replacement after an unconfirmed admission.
                    open_api_store.fail(row, 'ADMISSION_INTERRUPTED', '任务接收中断，请联系管理员核对原请求', False)
                    raise
            return {'request_id': request.state.open_request_id, 'data': task(row)}

    @router.get('/transcriptions/{task_id}', response_model=TaskResponse, summary='查询任务状态和结果')
    def query(task_id: str, request: Request, principal=Depends(open_api_auth.require_key)):
        limited(principal, 'read')
        with submission_lock:
            open_api_store.recover()
            data = task(open_api_store.lookup(principal['user_id'], task_id))
        return {'request_id': request.state.open_request_id, 'data': data}

    @router.get('/transcriptions/{task_id}/file', summary='导出 TXT 或 SRT', response_class=Response,
                responses={200: {'content': {'text/plain': {'schema': {'type': 'string'}}}}})
    def export(task_id: str, format: Literal['txt', 'srt'] = 'txt', principal=Depends(open_api_auth.require_key)):
        limited(principal, 'read')
        with submission_lock:
            open_api_store.recover()
            data = task(open_api_store.lookup(principal['user_id'], task_id))
        if data.status != 'succeeded' or data.result is None:
            raise AccountError('RESULT_NOT_READY', '文稿尚未生成，请查询原任务状态', 409)
        content = data.result.srt if format == 'srt' else data.result.text
        return Response(content, media_type='text/plain; charset=utf-8', headers={
            'X-Content-Type-Options': 'nosniff', 'Content-Disposition': "attachment; filename*=UTF-8''" + quote((data.title or '视频文稿') + '.' + format, safe='')})

    @router.get('/quota', response_model=QuotaResponse, summary='查询共享识别时长额度')
    def quota(request: Request, principal=Depends(open_api_auth.require_key)):
        limited(principal, 'read')
        return {'request_id': request.state.open_request_id, 'data': membership.summary(principal['user_id'])}

    return router


account_router = APIRouter(prefix='/api/account/api-keys', tags=['开发者密钥'])


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=50)


@account_router.get('')
def list_keys(response: Response, user=Depends(account_auth.require_user)):
    response.headers['Cache-Control'] = 'no-store'
    return open_api_store.keys(user['id'])


@account_router.post('', status_code=201)
def create_key(req: KeyRequest, request: Request, response: Response, user=Depends(account_auth.require_user)):
    account_auth.check_origin(request)
    account_auth.rate_limit(f"api-key-create:{user['id']}", 10, 600)
    response.headers['Cache-Control'] = 'no-store'
    return open_api_store.create_key(user['id'], user['session_id'], req.name)


@account_router.delete('/{key_id}')
def revoke_key(key_id: str, request: Request, response: Response, user=Depends(account_auth.require_user)):
    account_auth.check_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    open_api_store.revoke_key(user['id'], key_id)
    return {'ok': True}


def public_schema(router):
    schema = get_openapi(title='FreeVideo 视频文案提取开放 API', version='1.0.0', routes=router.routes)
    # Header belongs to the contract, not an undocumented implementation detail.
    schema['paths']['/api/open/v1/transcriptions']['post'].setdefault('parameters', []).append({
        'name': 'Idempotency-Key', 'in': 'header', 'required': True,
        'schema': {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': '^[A-Za-z0-9_.:-]+$'},
        'description': '同一账号、相同键与参数返回原任务；参数不同返回 409；保留期 30 天。'})
    return schema
