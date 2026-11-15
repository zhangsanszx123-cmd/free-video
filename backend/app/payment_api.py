"""Membership purchase endpoints and the ZPAY async notify callback."""
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import payments, transcription_auth
from .account_auth import require_user
from .zpay_mock import request_params

router = APIRouter(tags=["payments"])


class OrderReq(BaseModel):
    plan: Literal["monthly", "yearly"]
    pay_type: Literal['alipay'] = 'alipay'


@router.post("/api/pay/orders")
def create(req: OrderReq, request: Request, response: Response, user: dict = Depends(require_user)):
    transcription_auth.check_origin(request)
    response.headers["Cache-Control"] = "no-store"
    return payments.create_order(user["id"], req.plan)


@router.get("/api/pay/orders")
def orders(response: Response, user: dict = Depends(require_user)):
    response.headers["Cache-Control"] = "no-store"
    return {"orders": payments.list_orders(user["id"])}


@router.get("/api/pay/orders/{out_trade_no}")
def status(out_trade_no: str, response: Response, user: dict = Depends(require_user)):
    response.headers["Cache-Control"] = "no-store"
    return payments.order_status(user["id"], out_trade_no)


@router.api_route("/api/pay/notify", methods=["GET", "POST"], include_in_schema=False)
async def notify(request: Request):
    # Server-to-server: no login/origin check; authenticity comes from the signature + order query.
    params = await request_params(request)
    result = await run_in_threadpool(payments.handle_notify, params)
    return PlainTextResponse(result, headers={"Cache-Control": "no-store"})
