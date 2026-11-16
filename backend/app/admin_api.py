"""Administrative APIs with independent authentication and explicit response fields."""
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import account_auth as passwords
from . import admin_auth as auth, admin_store
from .errors import AccountError


def _no_store(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/admin', tags=['admin'], dependencies=[Depends(_no_store)])


class AdminBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LoginReq(AdminBody):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class OwnPasswordReq(AdminBody):
    old_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class StaffReq(AdminBody):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    nickname: str = Field(max_length=64)
    role: Literal['superadmin', 'admin'] = 'admin'
    status: Literal['active', 'disabled'] = 'active'


class StaffPatchReq(AdminBody):
    nickname: str | None = Field(default=None, max_length=64)
    role: Literal['superadmin', 'admin'] | None = None
    status: Literal['active', 'disabled'] | None = None


class ResetStaffPasswordReq(AdminBody):
    password: str = Field(max_length=256)


class UserStatusReq(AdminBody):
    status: Literal['active', 'disabled']
    reason: str = Field(default='', max_length=500)


@router.post('/auth/login')
def login(req: LoginReq, request: Request, response: Response):
    auth.check_origin(request)
    token, admin = auth.login(request, req.username, req.password)
    auth.set_cookie(response, token)
    return {'admin': admin}


@router.post('/auth/logout')
def logout(request: Request, response: Response):
    auth.check_origin(request)
    auth.revoke_current(request)
    auth.clear_cookie(response)
    return {'ok': True}


@router.get('/auth/me')
def me(request: Request, response: Response):
    admin = auth.current_admin(request)
    if not admin and auth.COOKIE in request.cookies:
        auth.clear_cookie(response)
    return {'admin': admin_store.public_admin(admin) if admin else None}


@router.post('/auth/password')
def change_password(req: OwnPasswordReq, request: Request, response: Response, actor: dict = Depends(auth.require_admin)):
    auth.check_origin(request)
    auth.change_password(actor, req.old_password, req.new_password)
    auth.clear_cookie(response)
    return {'ok': True}


@router.get('/users')
def users(page: int = Query(1, ge=1, le=100000), search: str = Query('', max_length=100),
          status: Literal['all', 'active', 'disabled'] = 'all', verified: Literal['all', 'verified', 'pending'] = 'all',
          actor: dict = Depends(auth.require_admin)):
    return admin_store.list_users(page, search.strip(), status, verified)


@router.get('/users/{user_id}')
def user_detail(user_id: int = Path(ge=1), actor: dict = Depends(auth.require_admin)):
    return admin_store.get_user(user_id)


@router.patch('/users/{user_id}/status')
def user_status(req: UserStatusReq, request: Request, user_id: int = Path(ge=1), actor: dict = Depends(auth.require_admin)):
    auth.check_origin(request)
    return {'user': admin_store.set_user_status(actor, user_id, req.status, req.reason)}


@router.get('/staff')
def staff(page: int = Query(1, ge=1, le=100000), search: str = Query('', max_length=100),
          status: Literal['all', 'active', 'disabled'] = 'all', actor: dict = Depends(auth.require_superadmin)):
    return admin_store.list_staff(page, search.strip(), status)


@router.post('/staff')
def create_staff(req: StaffReq, request: Request, actor: dict = Depends(auth.require_superadmin)):
    auth.check_origin(request)
    username = auth.normalize_username(req.username)
    nickname = auth.normalize_nickname(req.nickname)
    auth.validate_password(req.password, username)
    result = admin_store.create_staff(actor, username, nickname, passwords.hash_password(req.password), req.role, req.status)
    return {'admin': result}


@router.patch('/staff/{admin_id}')
def edit_staff(req: StaffPatchReq, request: Request, admin_id: int = Path(ge=1), actor: dict = Depends(auth.require_superadmin)):
    auth.check_origin(request)
    changes = req.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise AccountError('ADMIN_INVALID_STAFF', '后台账号字段不能为空', 422)
    if 'nickname' in changes:
        changes['nickname'] = auth.normalize_nickname(changes['nickname'])
    return {'admin': admin_store.update_staff(actor, admin_id, changes)}


@router.post('/staff/{admin_id}/password')
def reset_staff_password(req: ResetStaffPasswordReq, request: Request, response: Response,
                         admin_id: int = Path(ge=1), actor: dict = Depends(auth.require_superadmin)):
    auth.check_origin(request)
    target = admin_store.get_staff(admin_id)
    auth.validate_password(req.password, target['username'])
    result = admin_store.reset_staff_password(actor, admin_id, passwords.hash_password(req.password))
    if admin_id == actor['id']:
        auth.clear_cookie(response)
    return {'ok': True, 'admin': result}
