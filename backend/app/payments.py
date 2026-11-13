"""ZPAY membership orders: server-side price snapshot, idempotent fulfilment and reconciliation.

Every confirmation path (async notify, result-page query, background reconcile) ends in fulfil(),
which locks the user row and the order row in one transaction, so a payment is applied exactly once.
"""
import json
import logging
import math
import secrets
import threading
from datetime import datetime, timedelta

from . import account_auth, config, membership, zpay
from . import account_store as store
from .errors import AccountError

log = logging.getLogger("freevideo.payments")
PAID_PLANS = ("monthly", "yearly")
PAY_TYPE = "alipay"
QUERY_INTERVAL = timedelta(seconds=5)


def new_trade_no() -> str:
    """26 digits: Beijing time to the microsecond + 6 random digits (ZPAY allows up to 32)."""
    return datetime.now(membership.TZ).strftime("%Y%m%d%H%M%S%f") + f"{secrets.randbelow(10 ** 6):06d}"


def subject(plan) -> str:
    seconds = plan["monthly_seconds"]
    label = f"{seconds // 3600}小时" if seconds % 3600 == 0 else f"{math.ceil(seconds / 60)}分钟"
    return f"FreeVideo Pro {plan['name']}（视频转文字{label}/月）"


def _event(cur, out_trade_no, action, detail=None):
    clean = {k: v for k, v in (detail or {}).items() if k not in ("sign", "key")}
    cur.execute("INSERT INTO payment_events (out_trade_no,action,detail,created_at) VALUES (%s,%s,%s,%s)",
                (str(out_trade_no)[:64], action, json.dumps(clean, ensure_ascii=False, default=str), store.utcnow()))


def _active(cur, uid):
    now = store.utcnow()
    cur.execute("SELECT * FROM user_memberships WHERE user_id=%s AND starts_at<=%s AND expires_at>%s", (uid, now, now))
    return cur.fetchone()


def outcome(active, plan_code, months, now):
    """Confirmed rules: same plan extends; monthly -> yearly switches now and keeps the remaining time;
    buying monthly during an active yearly membership is refused."""
    if not active:
        return "new", membership.months_after(now, months)
    if active["plan_code"] == plan_code:
        return "renew", membership.renewal_expiry(active["starts_at"], active["expires_at"], months)
    if active["plan_code"] == "monthly" and plan_code == "yearly":
        return "upgrade", membership.months_after(now, months) + (active["expires_at"] - now)
    return "refused", None


def public(order) -> dict:
    expired = order["status"] == "pending" and order["created_at"] <= store.utcnow() - timedelta(
        minutes=config.PAYMENT_ORDER_TTL_MINUTES)
    return dict(out_trade_no=order["out_trade_no"], plan_code=order["plan_code"], plan_name=order["plan_name"],
                subject=order["subject"], amount=zpay.money(order["price_cents"]), price_cents=order["price_cents"],
                pay_type=order["pay_type"], status=order["status"], fulfilment=order["fulfilment"], expired=expired,
                created_at=membership.iso(order["created_at"]), paid_at=membership.iso(order["paid_at"]),
                membership_expires_at=membership.iso(order["membership_expires_at"]))


def _get(out_trade_no):
    if not out_trade_no or len(out_trade_no) > 32:
        return None
    with store._cursor() as cur:
        cur.execute("SELECT * FROM payment_orders WHERE out_trade_no=%s", (out_trade_no,))
        return cur.fetchone()


def create_order(uid: int, plan_code: str) -> dict:
    if not zpay.enabled():
        raise AccountError("PAYMENT_DISABLED", "在线支付暂未开放", 503)
    if plan_code not in PAID_PLANS:
        raise AccountError("INVALID_PLAN", "请选择月卡或年卡", 422)
    account_auth.rate_limit(f"pay:{uid}", 10, 600, "下单过于频繁，请稍后再试")
    with store._cursor() as cur:
        membership._lock_user(cur, uid)
        cur.execute("SELECT * FROM membership_plans WHERE code=%s", (plan_code,))
        plan = cur.fetchone()
        if not plan or not plan["months"] or not plan["price_cents"]:
            raise AccountError("PLAN_UNAVAILABLE", "套餐配置暂不可用", 503)
        now = store.utcnow()
        kind, expires = outcome(_active(cur, uid), plan_code, plan["months"], now)
        if kind == "refused":
            raise AccountError("PLAN_DOWNGRADE", "年卡会员有效期内不能购买月卡，可直接续费年卡", 409)
        # Reuse a recent unpaid order of the same price so double clicks never create two payable orders.
        cur.execute("SELECT * FROM payment_orders WHERE user_id=%s AND plan_code=%s AND status='pending' AND created_at>%s "
                    "AND price_cents=%s AND revision=%s ORDER BY created_at DESC LIMIT 1",
                    (uid, plan_code, now - timedelta(minutes=config.PAYMENT_ORDER_TTL_MINUTES),
                     plan["price_cents"], plan["revision"]))
        order = cur.fetchone()
        if not order:
            order = dict(out_trade_no=new_trade_no(), user_id=uid, plan_code=plan_code, plan_name=plan["name"],
                         price_cents=plan["price_cents"], monthly_seconds=plan["monthly_seconds"], months=plan["months"],
                         revision=plan["revision"], subject=subject(plan), pay_type=PAY_TYPE, status="pending",
                         trade_no=None, fulfilment=None, membership_expires_at=None, created_at=now, paid_at=None,
                         last_checked_at=None)
            cur.execute("INSERT INTO payment_orders (out_trade_no,user_id,plan_code,plan_name,price_cents,monthly_seconds,"
                        "months,revision,subject,pay_type,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (order["out_trade_no"], uid, plan_code, order["plan_name"], order["price_cents"],
                         order["monthly_seconds"], order["months"], order["revision"], order["subject"], PAY_TYPE,
                         "pending", now))
            _event(cur, order["out_trade_no"], "create", {"plan": plan_code, "price_cents": order["price_cents"]})
    action, fields = zpay.submit_form(order["out_trade_no"], order["subject"], order["price_cents"], order["pay_type"])
    return {"order": public(order), "action": action, "fields": fields,
            "preview": {"fulfilment": kind, "expires_at": membership.iso(expires)}}


def fulfil(out_trade_no: str, trade_no: str, paid_cents, source: str):
    """Apply a verified payment exactly once. Returns the order row (status stays 'pending' on mismatch)."""
    with store._cursor() as cur:
        cur.execute("SELECT user_id FROM payment_orders WHERE out_trade_no=%s", (out_trade_no,))
        row = cur.fetchone()
        if not row:
            return None
        if row["user_id"] is not None:
            # Same lock order as quota transactions: user row first, then the order.
            cur.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (row["user_id"],))
        cur.execute("SELECT * FROM payment_orders WHERE out_trade_no=%s FOR UPDATE", (out_trade_no,))
        order = cur.fetchone()
        if order["status"] != "pending":
            if trade_no and order["trade_no"] and trade_no != order["trade_no"]:
                _event(cur, out_trade_no, "conflict", {"reason": "second trade_no", "trade_no": trade_no, "source": source})
            return order
        if paid_cents != order["price_cents"]:
            _event(cur, out_trade_no, "conflict", {"reason": "amount", "paid_cents": paid_cents, "source": source})
            log.error("Payment amount mismatch for %s: %s != %s", out_trade_no, paid_cents, order["price_cents"])
            return order
        if trade_no:
            cur.execute("SELECT out_trade_no FROM payment_orders WHERE trade_no=%s", (trade_no,))
            if cur.fetchone():
                _event(cur, out_trade_no, "conflict", {"reason": "trade_no reused", "trade_no": trade_no, "source": source})
                return order
        now = store.utcnow()
        kind, expires = "refused", None
        uid = order["user_id"]
        if uid is not None:
            active = _active(cur, uid)
            kind, expires = outcome(active, order["plan_code"], order["months"], now)
            if kind != "refused":
                membership.apply_membership(cur, uid, order, active["starts_at"] if active else now, expires)
        status = "refund_required" if kind == "refused" else "paid"
        fulfilment = "none" if kind == "refused" else kind
        cur.execute("UPDATE payment_orders SET status=%s,trade_no=%s,fulfilment=%s,membership_expires_at=%s,paid_at=%s "
                    "WHERE out_trade_no=%s", (status, trade_no or None, fulfilment, expires, now, out_trade_no))
        _event(cur, out_trade_no, "fulfil", {"source": source, "status": status, "fulfilment": fulfilment,
                                              "trade_no": trade_no, "expires_at": expires})
        order.update(status=status, trade_no=trade_no or None, fulfilment=fulfilment, membership_expires_at=expires,
                     paid_at=now)
        if status == "refund_required":
            log.warning("Payment %s needs a refund (plan rule or deleted account)", out_trade_no)
        return order


def confirm(out_trade_no: str, source: str):
    """Ask ZPAY for the order state and fulfil if paid. Raises zpay.ZpayError when ZPAY is unreachable."""
    order = _get(out_trade_no)
    if not order or order["status"] != "pending":
        return order
    result = zpay.query_order(out_trade_no)
    if not result["paid"]:
        return order
    pid, _ = zpay.credentials()
    if (result.get("pid") and result["pid"] != pid) or (result.get("type") and result["type"] != order["pay_type"]):
        with store._cursor() as cur:
            _event(cur, out_trade_no, "conflict", {"reason": "query pid/type", "source": source})
        return order
    return fulfil(out_trade_no, result["trade_no"], result["money_cents"], source)


def handle_notify(params: dict) -> str:
    """ZPAY async notify. Only the exact text 'success' stops ZPAY's retries."""
    params = {k: str(v) for k, v in params.items()}
    out_trade_no = params.get("out_trade_no", "")
    if not zpay.enabled() or not zpay.verify(params):
        log.warning("Rejected ZPAY notify with invalid signature (order %s)", out_trade_no[:32])
        return "fail"
    if params.get("pid") != zpay.credentials()[0] or params.get("trade_status") != "TRADE_SUCCESS":
        return "fail"
    order = _get(out_trade_no)
    if not order:
        return "fail"
    if order["status"] != "pending":
        return "success"
    if zpay.cents(params.get("money")) != order["price_cents"] or params.get("type") != order["pay_type"]:
        with store._cursor() as cur:
            _event(cur, out_trade_no, "conflict", {"reason": "notify amount/type", "money": params.get("money"),
                                                   "type": params.get("type")})
        return "fail"
    # Signed notify is necessary but not sufficient: confirm with the order-query API (official advice).
    try:
        result = confirm(out_trade_no, "notify")
    except zpay.ZpayError:
        return "fail"
    return "success" if result and result["status"] != "pending" else "fail"


def _claim_check(out_trade_no: str, interval: timedelta) -> bool:
    """Atomically rate-limit gateway queries per order (several tabs or the reconciler may poll)."""
    now = store.utcnow()
    with store._cursor() as cur:
        return cur.execute("UPDATE payment_orders SET last_checked_at=%s WHERE out_trade_no=%s AND status='pending' "
                           "AND (last_checked_at IS NULL OR last_checked_at<=%s)",
                           (now, out_trade_no, now - interval)) > 0


def order_status(uid: int, out_trade_no: str) -> dict:
    order = _get(out_trade_no)
    if not order or order["user_id"] != uid:
        raise AccountError("NOT_FOUND", "订单不存在", 404)
    if order["status"] == "pending" and zpay.enabled() and _claim_check(out_trade_no, QUERY_INTERVAL):
        try:
            order = confirm(out_trade_no, "result_page") or order
        except zpay.ZpayError:
            pass
    return public(order)


def list_orders(uid: int) -> list[dict]:
    with store._cursor() as cur:
        cur.execute("SELECT * FROM payment_orders WHERE user_id=%s ORDER BY created_at DESC LIMIT 20", (uid,))
        return [public(row) for row in cur.fetchall()]


def reconcile(limit: int = 20) -> int:
    """Without a public IP ZPAY cannot reach notify_url; poll recent unpaid orders instead."""
    now = store.utcnow()
    with store._cursor() as cur:
        cur.execute("SELECT out_trade_no FROM payment_orders WHERE status='pending' AND created_at>%s "
                    "ORDER BY created_at DESC LIMIT %s", (now - timedelta(hours=24), limit))
        numbers = [row["out_trade_no"] for row in cur.fetchall()]
    done = 0
    for number in numbers:
        if not _claim_check(number, timedelta(seconds=30)):
            continue
        try:
            order = confirm(number, "reconcile")
            done += bool(order and order["status"] != "pending")
        except zpay.ZpayError:
            break  # gateway unreachable: try again next round
    return done


class Reconciler:
    def __init__(self):
        self.stopping = threading.Event()

    def start(self):
        if config.PAYMENT_RECONCILE_SECONDS <= 0 or not zpay.enabled():
            return
        self.stopping.clear()
        threading.Thread(target=self._run, name="payment-reconcile", daemon=True).start()

    def _run(self):
        while not self.stopping.wait(config.PAYMENT_RECONCILE_SECONDS):
            try:
                reconcile()
            except Exception:  # noqa: BLE001 - keep the loop alive; DB may be temporarily down
                log.exception("Payment reconcile failed")

    def stop(self):
        self.stopping.set()


def refund(out_trade_no: str, allow_paid: bool = False) -> str:
    """Operator-only full refund through ZPAY. Paid orders keep the granted membership (revoke manually)."""
    order = _get(out_trade_no)
    if not order:
        raise ValueError("订单不存在")
    allowed = ("refund_required", "paid") if allow_paid else ("refund_required",)
    if order["status"] not in allowed:
        raise ValueError(f"订单状态为 {order['status']}，不能退款" + ("（已开通会员的订单需加 --allow-paid）" if order["status"] == "paid" else ""))
    ok, message = zpay.refund(out_trade_no, order["price_cents"])
    with store._cursor() as cur:
        _event(cur, out_trade_no, "refund", {"ok": ok, "message": message})
        if ok:
            cur.execute("UPDATE payment_orders SET status='refunded' WHERE out_trade_no=%s AND status=%s",
                        (out_trade_no, order["status"]))
    if not ok:
        raise ValueError(f"退款失败：{message or '支付平台未返回原因'}")
    return message or "退款成功"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="本机支付订单管理")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("orders", help="查看最近 50 笔订单")
    listing.add_argument("--status", choices=["pending", "paid", "refund_required", "refunded"])
    sync = sub.add_parser("sync", help="向 ZPAY 查单并入账；不填单号则核对 24 小时内全部待支付订单")
    sync.add_argument("out_trade_no", nargs="?")
    back = sub.add_parser("refund", help="全额退款")
    back.add_argument("out_trade_no")
    back.add_argument("--allow-paid", action="store_true", help="允许退款已开通会员的订单（会员不会自动收回）")
    args = parser.parse_args()
    store.init_schema()
    if args.command == "orders":
        with store._cursor() as cur:
            where, values = ("WHERE status=%s", (args.status,)) if args.status else ("", ())
            cur.execute(f"SELECT * FROM payment_orders {where} ORDER BY created_at DESC LIMIT 50", values)
            rows = [{**public(r), "user_id": r["user_id"], "trade_no": r["trade_no"]} for r in cur.fetchall()]
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    elif args.command == "sync":
        if args.out_trade_no:
            result = confirm(args.out_trade_no, "cli")
            print(json.dumps(public(result) if result else None, ensure_ascii=False))
        else:
            print(f"已入账 {reconcile(limit=200)} 笔")
    else:
        print(refund(args.out_trade_no, args.allow_paid))
