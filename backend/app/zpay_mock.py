"""Development-only fake ZPAY cashier (ZPAY_MOCK=true, refused when SESSION_SECURE=true).

Mimics submit.php / api.php closely enough to exercise signing, async notify, return_url,
order query and refund on one machine without spending money. State is in memory.
"""
import html
import logging
import secrets
import threading
from datetime import datetime
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import zpay

log = logging.getLogger("freevideo.zpay_mock")
router = APIRouter(prefix="/api/pay/mock", include_in_schema=False)
_lock = threading.Lock()
_orders: dict[str, dict] = {}


async def request_params(request: Request) -> dict:
    params = dict(request.query_params)
    if request.method == "POST":
        params.update(parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True))
    return params


def _guard():
    if not zpay.mock_active():
        raise HTTPException(404)


def _page(title: str, body: str, refresh: str = "") -> HTMLResponse:
    meta = f'<meta http-equiv="refresh" content="2;url={html.escape(refresh)}">' if refresh else ""
    return HTMLResponse(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}<title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;background:#f1f5f9;margin:0;padding:24px}}
main{{max-width:440px;margin:0 auto;background:#fff;border-radius:20px;padding:24px;box-shadow:0 10px 30px #0001}}
.warn{{background:#fef3c7;color:#92400e;border-radius:12px;padding:10px 12px;font-weight:700}}
button{{width:100%;min-height:48px;margin-top:10px;border:0;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer}}
.pay{{background:#1677ff;color:#fff}}.alt{{background:#e2e8f0;color:#0f172a}}dt{{color:#64748b;margin-top:10px}}dd{{margin:2px 0 0}}</style>
</head><body><main>{body}</main></body></html>""", headers={"Cache-Control": "no-store"})


@router.api_route("/submit.php", methods=["GET", "POST"])
async def submit(request: Request):
    _guard()
    params = await request_params(request)
    if not zpay.verify(params):
        return JSONResponse({"code": "error", "msg": "签名错误"})
    if params.get("pid") != zpay.credentials()[0] or params.get("type") != "alipay":
        return JSONResponse({"code": "error", "msg": "商户或支付方式无效"})
    number = params.get("out_trade_no", "")
    with _lock:
        existing = _orders.get(number)
        if existing and existing["status"] == 1:
            return JSONResponse({"code": "error", "msg": "该订单已支付，请勿重复付款"})
        _orders[number] = {**params, "status": 0, "trade_no": "", "addtime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           "endtime": ""}
    e = html.escape
    buttons = "".join(f'<button class="{cls}" name="action" value="{value}">{label}</button>' for value, label, cls in [
        ("paid", "模拟支付成功", "pay"), ("paid_silent", "支付成功但不发异步通知（测试主动查单）", "alt"),
        ("paid_twice", "支付成功并重复发送 3 次通知（测试幂等）", "alt"), ("cancel", "取消支付", "alt")])
    return _page("ZPAY 模拟收银台", f"""<p class="warn">模拟支付 · 不会扣钱 · 仅限本机开发测试</p>
<h1>支付宝收银台（模拟）</h1><dl><dt>商品</dt><dd>{e(params.get('name', ''))}</dd>
<dt>金额</dt><dd style="font-size:28px;font-weight:800">¥{e(params.get('money', ''))}</dd>
<dt>商户订单号</dt><dd>{e(number)}</dd></dl>
<form method="post" action="/api/pay/mock/pay"><input type="hidden" name="out_trade_no" value="{e(number)}">{buttons}</form>""")


def _callback(order: dict) -> dict:
    params = {"pid": order["pid"], "trade_no": order["trade_no"], "out_trade_no": order["out_trade_no"],
              "type": order["type"], "name": order["name"], "money": order["money"], "trade_status": "TRADE_SUCCESS"}
    return {**params, "sign": zpay.sign(params), "sign_type": "MD5"}


def send_notify(order: dict) -> str:
    """Server-to-server GET like the real gateway."""
    try:
        return httpx.get(order["notify_url"], params=_callback(order), timeout=5).text.strip()[:50]
    except httpx.HTTPError as e:
        log.warning("Mock notify to %s failed: %s", order["notify_url"], e)
        return f"通知失败：{type(e).__name__}（检查 PUBLIC_BASE_URL）"


@router.post("/pay")
async def pay(request: Request):
    _guard()
    params = await request_params(request)
    with _lock:
        order = _orders.get(params.get("out_trade_no", ""))
        if not order:
            raise HTTPException(404, "模拟订单不存在")
        if params.get("action") == "cancel":
            return _page("已取消", "<h1>已取消支付</h1><p>正在返回定价页…</p>", "/pricing")
        if order["status"] != 1:
            order.update(status=1, trade_no=datetime.now().strftime("%Y%m%d%H%M%S") + f"{secrets.randbelow(10 ** 8):08d}",
                         endtime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        order = dict(order)
    action = params.get("action")
    # Off the event loop: the notify request is served by this same process.
    results = [] if action == "paid_silent" else [
        await run_in_threadpool(send_notify, order) for _ in range(3 if action == "paid_twice" else 1)]
    target = order["return_url"] + "?" + urlencode(_callback(order))
    note = "未发送异步通知" if not results else "异步通知应答：" + "、".join(html.escape(r) for r in results)
    return _page("支付成功", f"<h1>模拟支付成功</h1><p>{note}</p><p>2 秒后跳回商户页面… "
                            f'<a href="{html.escape(target)}">立即返回</a></p>', target)


def query(out_trade_no: str) -> dict:
    with _lock:
        order = _orders.get(out_trade_no)
        if not order:
            return {"code": -1, "msg": "订单不存在"}
        return {"code": 1, "msg": "查询订单号成功！", "trade_no": order["trade_no"], "out_trade_no": out_trade_no,
                "type": order["type"], "pid": order["pid"], "addtime": order["addtime"], "endtime": order["endtime"],
                "name": order["name"], "money": order["money"], "status": order["status"], "param": "", "buyer": ""}


def refund(out_trade_no: str) -> dict:
    with _lock:
        order = _orders.get(out_trade_no)
        if not order or order["status"] != 1:
            return {"code": -1, "msg": "订单未支付，无法退款"}
        order["status"] = 0
        return {"code": 1, "msg": "退款成功"}


@router.get("/api.php")
def api(act: str, out_trade_no: str = ""):
    _guard()
    if act == "order":
        return query(out_trade_no)
    return {"code": -1, "msg": "模拟网关仅支持 act=order"}


def reset():
    with _lock:
        _orders.clear()
