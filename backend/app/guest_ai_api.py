"""Dedicated visitor trial routes; account and developer API protections stay intact."""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import account_auth, guest, transcription_auth
from .errors import AccountError, VideoError


class TrialRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=1, max_length=2000)


def create_router(get_manager):
    router = APIRouter(prefix='/api/guest/ai-summary', tags=['游客 AI 体验'])

    def identity(request, response, create=False):
        transcription_auth.check_origin(request)
        response.headers['Cache-Control'] = 'no-store'
        owner, subjects = guest.trial_identity(request, response)
        account_auth.rate_limit('guest-ai-' + ('create:' if create else 'read:') + owner,
                                10 if create else 60, 60)
        account_auth.rate_limit('guest-ai-ip-' + ('create:' if create else 'read:') + account_auth.peer(request),
                                10 if create else 180, 60)
        return owner, subjects

    @router.get('')
    def status(request: Request, response: Response):
        owner, subjects = identity(request, response)
        return get_manager().status(owner, subjects)

    @router.post('', status_code=202)
    def submit(req: TrialRequest, request: Request, response: Response):
        owner, subjects = identity(request, response, True)
        try:
            return get_manager().submit(owner, subjects, req.url)
        except AccountError:
            raise
        except VideoError as exc:
            raise AccountError('INVALID_URL', str(exc), 422) from None

    @router.get('/{trial_id}')
    def query(trial_id: str, request: Request, response: Response):
        owner, _ = identity(request, response)
        return get_manager().get(owner, trial_id)

    return router
