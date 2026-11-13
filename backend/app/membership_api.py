"""Read-only public plans and account-scoped quota/history endpoints."""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response

from . import membership, transcription_auth, zpay
from .account_auth import require_user
from .errors import TranscriptionError

router = APIRouter(tags=['membership'])


@router.get('/api/plans')
def plans(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {'plans': membership.plans(), 'payment_enabled': zpay.enabled()}


@router.get('/api/account/membership')
def summary(response: Response, user: dict = Depends(require_user)):
    response.headers['Cache-Control'] = 'no-store'
    return membership.summary(user['id'])


@router.get('/api/account/history')
def history(response: Response, page: int = Query(1, ge=1, le=100000), search: str = Query('', max_length=100),
            status: Literal['all', 'active', 'done', 'error'] = 'all', user: dict = Depends(require_user)):
    response.headers['Cache-Control'] = 'no-store'
    return membership.history(user['id'], page, search, status)


@router.get('/api/account/history/{job_id}')
def detail(job_id: str, response: Response, user: dict = Depends(require_user)):
    response.headers['Cache-Control'] = 'no-store'
    row = membership.record(user['id'], job_id=job_id)
    if not row or row['hidden']:
        raise TranscriptionError('NOT_FOUND', '记录不存在或已过期', status=404)
    return row['payload']


@router.get('/api/account/history/{job_id}/file')
def export(job_id: str, format: Literal['txt', 'srt'] = 'txt', user: dict = Depends(require_user)):
    row = membership.record(user['id'], job_id=job_id)
    if not row or row['hidden'] or row['status'] != 'done' or not row['payload'].get('result'):
        raise TranscriptionError('NOT_FOUND', '文稿尚未生成或已过期', status=404)
    content = row['payload']['result']['srt' if format == 'srt' else 'text']
    return Response(content, media_type='text/plain; charset=utf-8', headers={
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row['title'] + '.' + format, safe='')})


@router.delete('/api/account/history/{job_id}')
def delete(job_id: str, request: Request, response: Response, user: dict = Depends(require_user)):
    transcription_auth.check_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    membership.hide(user['id'], job_id)
    return {'ok': True}
