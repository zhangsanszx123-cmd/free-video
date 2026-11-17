"""ZPAY payment tests on the real MySQL test database; the gateway is the in-process mock or monkeypatched."""
import hashlib
import threading
from datetime import datetime, timedelta

import pytest

from app import account_store, config, membership, payments, zpay, zpay_mock
from .test_accounts import db, register, query, PASSWORD, make_client  # noqa: F401

pytestmark = pytest.mark.skipif(not config.MYSQL_TEST_DATABASE, reason='MYSQL_TEST_DATABASE not configured')


@pytest.fixture(autouse=True)
def setup(db, monkeypatch, client):
    query('DELETE FROM membership_plans')
    membership.seed()
    query('DELETE FROM payment_events')
    query('DELETE FROM payment_orders')
    zpay_mock.reset()
    monkeypatch.setattr(config, 'ZPAY_MOCK', True)
    monkeypatch.setattr(config, 'SESSION_SECURE', False)
    # The mock gateway notifies over HTTP; route it through the TestClient instead of a real socket.
    monkeypatch.setattr(zpay_mock, 'send_notify', lambda order: client.get(
        '/api/pay/notify', params=zpay_mock._callback(order)).text)


def uid(client, name='alice'):
    res = register(client, name)
    assert res.status_code == 200, res.text
    return res.json()['user']['id']


def quote(plan='monthly'):
    current = next(item for item in membership.plans() if item['code'] == plan)
    return {'plan': plan, 'expected_price_cents': current['price_cents'], 'expected_revision': current['revision']}


def test_checkout_requires_confirmed_current_price(client):
    uid(client)
    old = quote()
    assert client.post('/api/pay/orders', json={'plan': 'monthly'}).status_code == 422
    original = order(client)['order']
    membership.configure('monthly', 2990, 36000)
    for body in (old, {**old, 'expected_price_cents': 2990}, {**old, 'expected_revision': old['expected_revision'] + 1}):
        response = client.post('/api/pay/orders', json=body)
        assert response.status_code == 409 and response.json()['code'] == 'PLAN_PRICE_CHANGED'
    assert len(query('SELECT * FROM payment_orders')) == 1
    assert row(original['out_trade_no'])['price_cents'] == original['price_cents']
    assert order(client)['order']['price_cents'] == 2990


def test_old_order_keeps_price_but_uses_live_quota(client):
    user = uid(client)
    original = order(client)['order']
    membership.configure('monthly', 2990, 600)
    payments.fulfil(original['out_trade_no'], 'quota-live-trade', original['price_cents'], 'test')
    assert row(original['out_trade_no'])['price_cents'] == 1990
    assert membership.summary(user)['limit_seconds'] == 600


def order(client, plan='monthly'):
    res = client.post('/api/pay/orders', json=quote(plan))
    assert res.status_code == 200, res.text
    return res.json()


def pay(client, plan='monthly', action='paid'):
    data = order(client, plan)
    page = client.post(data['action'], data=data['fields'])
    assert '模拟收银台' in page.text, page.text
    res = client.post('/api/pay/mock/pay', data={'out_trade_no': data['order']['out_trade_no'], 'action': action})
    assert res.status_code == 200
    return data['order']['out_trade_no']


def row(number):
    return query('SELECT * FROM payment_orders WHERE out_trade_no=%s', (number,))[0]


def ent(user):
    return query('SELECT * FROM user_memberships WHERE user_id=%s', (user,))[0]


def fulfil_events(number):
    return query("SELECT * FROM payment_events WHERE out_trade_no=%s AND action='fulfil'", (number,))


def signed(params):
    return {**params, 'sign': zpay.sign(params), 'sign_type': 'MD5'}


def test_sign_algorithm_and_money():
    params = {'name': '商品 A', 'money': '0.01', 'a': '', 'sign': 'x', 'sign_type': 'MD5', 'pid': '1001'}
    assert zpay.sign_string(params) == 'money=0.01&name=商品 A&pid=1001'
    assert zpay.sign(params, 'KEY') == hashlib.md5('money=0.01&name=商品 A&pid=1001KEY'.encode()).hexdigest()
    assert zpay.money(1990) == '19.90' and zpay.money(1) == '0.01'
    assert zpay.cents('19.9') == 1990 and zpay.cents('19.90') == 1990
    assert zpay.cents('19.901') is None and zpay.cents('abc') is None and zpay.cents('-1') is None


def test_disabled_and_validation(client, monkeypatch):
    uid(client)
    for method in ('wxpay', 'unknown'):
        assert client.post('/api/pay/orders', json={'plan': 'monthly', 'pay_type': method}).status_code == 422
    assert not query('SELECT out_trade_no FROM payment_orders')
    explicit = client.post('/api/pay/orders', json={**quote(), 'pay_type': 'alipay'})
    assert explicit.status_code == 200 and explicit.json()['fields']['type'] == 'alipay'
    assert client.post('/api/pay/orders', json={'plan': 'free'}).status_code == 422
    assert make_client().post('/api/pay/orders', json={'plan': 'monthly'}).status_code == 401
    assert client.post('/api/pay/orders', json=quote(), headers={'origin': 'https://evil.example'}).status_code == 403
    monkeypatch.setattr(config, 'SESSION_SECURE', True)  # mock is refused in production
    assert not zpay.enabled()
    assert client.post('/api/pay/orders', json=quote()).json()['code'] == 'PAYMENT_DISABLED'
    assert client.get('/api/plans').json()['payment_enabled'] is False
    assert client.get('/api/pay/mock/api.php', params={'act': 'order'}).status_code == 404


def test_order_uses_server_price_snapshot_and_reuses_pending(client):
    uid(client)
    first = order(client)
    fields = first['fields']
    assert first['action'] == '/api/pay/mock/submit.php' and zpay.verify(fields)
    assert fields['money'] == '19.90' and fields['type'] == 'alipay' and len(fields['out_trade_no']) == 26
    assert fields['notify_url'] == 'http://testserver/api/pay/notify' and fields['return_url'] == 'http://testserver/pay/result'
    assert 'key' not in fields and '视频转文字10小时' in fields['name']
    assert first['preview']['fulfilment'] == 'new'
    assert order(client)['order']['out_trade_no'] == first['order']['out_trade_no']
    membership.configure('monthly', 2990, 36000)
    second = order(client)
    assert second['order']['out_trade_no'] != first['order']['out_trade_no'] and second['fields']['money'] == '29.90'
    assert row(first['order']['out_trade_no'])['price_cents'] == 1990


def test_full_mock_flow_grants_membership(client):
    user = uid(client)
    number = pay(client)
    status = client.get(f'/api/pay/orders/{number}').json()
    assert status['status'] == 'paid' and status['fulfilment'] == 'new'
    summary = client.get('/api/account/membership').json()
    assert summary['plan'] == 'monthly' and summary['limit_seconds'] == 36000 and summary['payment_enabled'] is True
    assert client.get('/api/pay/orders').json()['orders'][0]['out_trade_no'] == number
    assert row(number)['trade_no'] and len(fulfil_events(number)) == 1
    other = make_client()
    uid(other, 'bob_01')
    assert other.get(f'/api/pay/orders/{number}').status_code == 404
    assert ent(user)['plan_code'] == 'monthly'


def test_notify_rejects_forged_or_mismatched_data(client):
    uid(client)
    number = order(client)['order']['out_trade_no']
    base = {'pid': zpay.MOCK_PID, 'trade_no': 'T1', 'out_trade_no': number, 'type': 'alipay', 'name': 'x',
            'money': '19.90', 'trade_status': 'TRADE_SUCCESS'}
    assert client.get('/api/pay/notify', params={**signed(base), 'sign': '0' * 32}).text == 'fail'
    assert client.get('/api/pay/notify', params=signed({**base, 'money': '0.01'})).text == 'fail'
    assert client.get('/api/pay/notify', params=signed({**base, 'trade_status': 'WAIT_BUYER_PAY'})).text == 'fail'
    assert client.get('/api/pay/notify', params=signed({**base, 'pid': 'other'})).text == 'fail'
    # Correctly signed (e.g. leaked key) but the gateway says unpaid: must not grant anything.
    assert client.get('/api/pay/notify', params=signed(base)).text == 'fail'
    assert row(number)['status'] == 'pending' and not fulfil_events(number)
    assert client.get('/api/pay/notify', params=signed({**base, 'out_trade_no': '1' * 26})).text == 'fail'


def test_duplicate_notifies_apply_once(client):
    user = uid(client)
    number = pay(client, action='paid_twice')
    assert row(number)['status'] == 'paid' and len(fulfil_events(number)) == 1
    assert ent(user)['expires_at'] == row(number)['membership_expires_at']
    callback = zpay_mock._callback(zpay_mock._orders[number])
    assert client.post('/api/pay/notify', data=callback).text == 'success'
    assert len(fulfil_events(number)) == 1


def test_concurrent_confirmation_paths_fulfil_exactly_once(client):
    user = uid(client)
    number = pay(client, action='paid_silent')
    assert row(number)['status'] == 'pending'
    callback = zpay_mock._callback(zpay_mock._orders[number])
    barrier = threading.Barrier(10)
    errors = []

    def worker(i):
        barrier.wait()
        try:
            [lambda: payments.handle_notify(callback), lambda: payments.confirm(number, 'test'), payments.reconcile][i % 3]()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert row(number)['status'] == 'paid' and len(fulfil_events(number)) == 1
    start = row(number)['paid_at']
    assert ent(user)['expires_at'] == membership.months_after(start, 1)


def test_result_page_query_without_notify_and_throttle(client, monkeypatch):
    uid(client)
    number = pay(client, action='paid_silent')
    calls = []
    real = zpay.query_order
    monkeypatch.setattr(zpay, 'query_order', lambda n: calls.append(n) or real(n))
    assert client.get(f'/api/pay/orders/{number}').json()['status'] == 'paid'
    assert len(calls) == 1
    pending = order(client, 'yearly')['order']['out_trade_no']
    client.get(f'/api/pay/orders/{pending}')
    client.get(f'/api/pay/orders/{pending}')
    assert calls.count(pending) == 1  # second poll within 5 seconds does not hit the gateway


def test_gateway_errors_never_mark_paid(client, monkeypatch):
    uid(client)
    number = pay(client, action='paid_silent')
    callback = zpay_mock._callback(zpay_mock._orders[number])

    def down(_):
        raise zpay.ZpayError('down')
    monkeypatch.setattr(zpay, 'query_order', down)
    assert client.get('/api/pay/notify', params=callback).text == 'fail'
    assert client.get(f'/api/pay/orders/{number}').json()['status'] == 'pending'


def test_renew_upgrade_and_refund_rules(client):
    user = uid(client)
    first = pay(client)
    first_end = ent(user)['expires_at']
    assert order(client)['preview']['fulfilment'] == 'renew'
    second = pay(client)
    assert row(second)['fulfilment'] == 'renew' and ent(user)['expires_at'] == membership.months_after(first_end, 1)
    remaining = ent(user)['expires_at'] - account_store.utcnow()
    stray = order(client, 'monthly')['order']['out_trade_no']  # abandoned in another tab
    third = pay(client, 'yearly')
    assert row(third)['fulfilment'] == 'upgrade'
    expected = membership.months_after(row(third)['paid_at'], 12) + remaining
    assert abs((ent(user)['expires_at'] - expected).total_seconds()) < 5
    assert ent(user)['plan_code'] == 'yearly' and membership.summary(user)['limit_seconds'] == 108000
    res = client.post('/api/pay/orders', json=quote())
    assert res.status_code == 409 and res.json()['code'] == 'PLAN_DOWNGRADE'
    # The stray monthly cashier is paid late: money is recorded, membership untouched, refund required.
    before = ent(user)['expires_at']
    page = client.post('/api/pay/mock/submit.php', data=zpay.submit_form(stray, row(stray)['subject'], 1990)[1])
    assert '模拟收银台' in page.text
    client.post('/api/pay/mock/pay', data={'out_trade_no': stray, 'action': 'paid'})
    assert row(stray)['status'] == 'refund_required' and ent(user)['expires_at'] == before
    with pytest.raises(ValueError, match='不能退款'):
        payments.refund(first)
    assert payments.refund(stray) == '退款成功' and row(stray)['status'] == 'refunded'


def test_late_payment_after_local_expiry_is_still_credited(client):
    uid(client)
    data = order(client)
    number = data['order']['out_trade_no']
    query('UPDATE payment_orders SET created_at=%s WHERE out_trade_no=%s', (account_store.utcnow() - timedelta(hours=2), number))
    assert client.get('/api/pay/orders').json()['orders'][0]['expired'] is True
    client.post(data['action'], data=data['fields'])
    client.post('/api/pay/mock/pay', data={'out_trade_no': number, 'action': 'paid'})
    assert row(number)['status'] == 'paid'
    assert order(client)['order']['out_trade_no'] != number


def test_paid_cycles_replace_free_and_renew_upgrade_preserve_usage(client, monkeypatch):
    clock = [datetime(2026, 11, 5, 2, 30)]
    monkeypatch.setattr(account_store, 'utcnow', lambda: clock[0])
    user = uid(client)
    free_job = 'a' * 32
    membership.reserve(user, free_job, 600, 'a' * 64)
    membership.finalize(user, free_job, 'settled')
    clock[0] = datetime(2026, 11, 7, 3, 45)
    first = pay(client)
    opening = ent(user)['starts_at']
    summary = membership.summary(user)
    assert summary['available_seconds'] == summary['limit_seconds'] == 36000
    assert summary['used_seconds'] == 0
    assert summary['resets_at'] == membership.iso(datetime(2026, 12, 7, 3, 45))
    assert summary['ends_with_membership']
    for job, seconds, state in [('b' * 32, 3600, 'settled'), ('c' * 32, 300, 'unknown')]:
        membership.reserve(user, job, seconds, job.ljust(64, '0'))
        membership.finalize(user, job, state)
    clock[0] = datetime(2026, 11, 8, 4)
    second = pay(client)
    renewed = membership.summary(user)
    assert second != first and ent(user)['starts_at'] == opening
    assert renewed['period_start'] == summary['period_start']
    assert renewed['resets_at'] == summary['resets_at']
    assert renewed['available_seconds'] == 32100 and not renewed['ends_with_membership']
    clock[0] = datetime(2026, 11, 9, 5)
    pay(client, 'yearly')
    upgraded = membership.summary(user)
    assert ent(user)['starts_at'] == opening
    assert upgraded['period_start'] == summary['period_start']
    assert upgraded['resets_at'] == summary['resets_at']
    assert upgraded['limit_seconds'] == 108000
    assert upgraded['used_seconds'] == 3600 and upgraded['reserved_seconds'] == 300
    assert upgraded['available_seconds'] == 104100
    clock[0] = datetime(2026, 12, 7, 3, 45)
    reset = membership.summary(user)
    assert reset['used_seconds'] == 0 and reset['pending_previous_seconds'] == 300
    membership.finalize(user, 'c' * 32, 'settled')
    assert membership.summary(user)['available_seconds'] == 108000


def test_orders_survive_account_deletion(client):
    user = uid(client)
    number = pay(client)
    assert client.request('DELETE', '/api/account', json={'password': PASSWORD, 'confirm_email': 'alice@example.com'}).status_code == 200
    assert row(number)['user_id'] is None and row(number)['status'] == 'paid'
    assert not query('SELECT * FROM user_memberships WHERE user_id=%s', (user,))


def test_mock_cashier_rejects_bad_signature_and_repeat_payment(client):
    uid(client)
    data = order(client)
    assert client.post(data['action'], data={**data['fields'], 'money': '0.01'}).json()['msg'] == '签名错误'
    client.post(data['action'], data=data['fields'])
    client.post('/api/pay/mock/pay', data={'out_trade_no': data['order']['out_trade_no'], 'action': 'paid'})
    assert '已支付' in client.post(data['action'], data=data['fields']).json()['msg']
