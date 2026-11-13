"""Thin ZPAY (易支付协议) client: MD5 signing, page-jump form, order query and refund.

Protocol reference: docs/zpay.md and https://z-pay.cn/doc.html.
"""
import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation

import httpx

from . import config

log = logging.getLogger("freevideo.zpay")
TIMEOUT = 3.0
MOCK_PID, MOCK_KEY = "mock-pid", "mock-key"


class ZpayError(Exception):
    """Gateway unreachable or returned an unusable answer; callers must not treat it as unpaid."""


def mock_active() -> bool:
    return config.ZPAY_MOCK and not config.SESSION_SECURE


def enabled() -> bool:
    return mock_active() or bool(config.ZPAY_PID and config.ZPAY_KEY)


def credentials() -> tuple[str, str]:
    if mock_active():
        return config.ZPAY_PID or MOCK_PID, config.ZPAY_KEY or MOCK_KEY
    if not (config.ZPAY_PID and config.ZPAY_KEY):
        raise ZpayError("ZPAY 未配置")
    return config.ZPAY_PID, config.ZPAY_KEY


def sign_string(params: dict) -> str:
    """Sorted k=v pairs, excluding sign/sign_type/empty values, values NOT url-encoded."""
    items = sorted((k, str(v)) for k, v in params.items()
                   if k not in ("sign", "sign_type") and v is not None and str(v) != "")
    return "&".join(f"{k}={v}" for k, v in items)


def sign(params: dict, key: str | None = None) -> str:
    key = key if key is not None else credentials()[1]
    return hashlib.md5((sign_string(params) + key).encode("utf-8")).hexdigest()


def verify(params: dict) -> bool:
    received = str(params.get("sign") or "")
    return bool(received) and hmac.compare_digest(received.lower(), sign(params))


def money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def cents(value) -> int | None:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        return None
    return int(amount * 100)


def gateway() -> str:
    return "/api/pay/mock" if mock_active() else config.ZPAY_GATEWAY


def submit_form(out_trade_no: str, subject: str, price_cents: int, pay_type: str = "alipay") -> tuple[str, dict]:
    pid, key = credentials()
    fields = {"pid": pid, "type": pay_type, "out_trade_no": out_trade_no,
              "notify_url": f"{config.PUBLIC_BASE_URL}/api/pay/notify",
              "return_url": f"{config.PUBLIC_BASE_URL}/pay/result",
              "name": subject, "money": money(price_cents)}
    fields["sign"] = sign(fields, key)
    fields["sign_type"] = "MD5"
    return f"{gateway()}/submit.php", fields


def _parse_order(data: dict, out_trade_no: str) -> dict:
    if str(data.get("code")) != "1":
        # "订单不存在" simply means the buyer never opened the cashier.
        return {"paid": False, "message": str(data.get("msg") or "")[:100]}
    if str(data.get("out_trade_no")) != out_trade_no:
        raise ZpayError("查单结果订单号不一致")
    return {"paid": str(data.get("status")) == "1", "money_cents": cents(data.get("money")),
            "trade_no": str(data.get("trade_no") or ""), "type": str(data.get("type") or ""),
            "pid": str(data.get("pid") or "")}


def query_order(out_trade_no: str) -> dict:
    """Ask ZPAY whether the order is paid. Raises ZpayError on network/format errors."""
    if mock_active():
        from . import zpay_mock
        return _parse_order(zpay_mock.query(out_trade_no), out_trade_no)
    pid, key = credentials()
    try:
        res = httpx.get(f"{config.ZPAY_GATEWAY}/api.php", timeout=TIMEOUT,
                        params={"act": "order", "pid": pid, "key": key, "out_trade_no": out_trade_no})
        res.raise_for_status()
        data = res.json()
    except (httpx.HTTPError, ValueError) as e:
        # Never log the URL: it carries the merchant key.
        log.warning("ZPAY order query failed for %s: %s", out_trade_no, type(e).__name__)
        raise ZpayError("支付平台查单失败") from e
    if not isinstance(data, dict):
        raise ZpayError("支付平台返回格式异常")
    return _parse_order(data, out_trade_no)


def refund(out_trade_no: str, price_cents: int) -> tuple[bool, str]:
    if mock_active():
        from . import zpay_mock
        data = zpay_mock.refund(out_trade_no)
    else:
        pid, key = credentials()
        try:
            res = httpx.post(f"{config.ZPAY_GATEWAY}/api.php", params={"act": "refund"}, timeout=10,
                             data={"pid": pid, "key": key, "out_trade_no": out_trade_no, "money": money(price_cents)})
            res.raise_for_status()
            data = res.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ZpayError("支付平台退款请求失败") from e
    return str(data.get("code")) == "1", str(data.get("msg") or "")
