"""Built frontend :8000, fully mocked APIs and cashier; no real data or payments."""
from copy import deepcopy
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:8000'
SHOTS = Path('.runtime/admin-pricing-ui')
SHOTS.mkdir(parents=True, exist_ok=True)
ADMIN = dict(id=1, username='owner', nickname='管理员', role='superadmin', status='active')
USER = dict(id=2, username='member', email='member@example.com', nickname='会员')
PLANS = [dict(code=code, name=name, months=months, price_cents=price, monthly_seconds=seconds,
              revision=1, ai_monthly_limit=300, chat_daily_limit=10, batch_max_links=10, asr_max_minutes=30)
         for code, name, months, price, seconds in [('free', '免费用户', 0, 0, 1800),
             ('monthly', '月卡会员', 1, 1990, 36000), ('yearly', '年卡会员', 12, 9900, 108000)]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        state = dict(plans=deepcopy(PLANS), role='superadmin', saves=[], orders=[], conflict=False, plan_reads=0)
        errors = []
        context = browser.new_context(viewport=dict(width=width, height=1000))
        context.add_init_script("window.cashierSubmits = []; HTMLFormElement.prototype.submit = function() { window.cashierSubmits.push(this.action) }")

        def api(route):
            path = route.request.url.split('/api/')[1].split('?')[0]
            if path == 'admin/auth/me':
                return route.fulfill(json={'admin': {**ADMIN, 'role': state['role']}})
            if path == 'auth/me': return route.fulfill(json={'user': USER})
            if path == 'account/membership':
                return route.fulfill(json=dict(plan='free', expires_at=None, remaining_seconds=1800, limit_seconds=1800))
            if path in ('plans', 'admin/plans'):
                if path == 'plans': state['plan_reads'] += 1
                return route.fulfill(json={'plans': [p for p in state['plans'] if path == 'plans' or p['code'] != 'free'], 'payment_enabled': True})
            if path.startswith('admin/plans/'):
                plan = next(p for p in state['plans'] if p['code'] == path.split('/')[2])
                body = route.request.post_data_json
                if state['conflict']:
                    state['conflict'] = False
                    plan['revision'] += 1; plan['price_cents'] += 100
                if body['revision'] != plan['revision']:
                    return route.fulfill(status=409, json=dict(code='ADMIN_PLAN_CONFLICT', detail='套餐已被修改，请刷新后重新确认价格'))
                state['saves'].append(body)
                plan['price_cents'] = body['price_cents']; plan['revision'] += 1
                return route.fulfill(json={'plan': plan})
            if path == 'pay/orders' and route.request.method == 'POST':
                body = route.request.post_data_json
                state['orders'].append(body)
                plan = next(p for p in state['plans'] if p['code'] == body['plan'])
                if body.get('expected_price_cents') != plan['price_cents'] or body.get('expected_revision') != plan['revision']:
                    return route.fulfill(status=409, json=dict(code='PLAN_PRICE_CHANGED', detail='套餐价格已更新，请查看最新金额后重新确认付款'))
                return route.fulfill(json=dict(order=dict(out_trade_no='mock-order'), action='/mock-cashier', fields={}))
            return route.fulfill(json=dict(ok=True, plans=[]))

        context.route('**/api/**', api)
        admin = context.new_page(); front = context.new_page()
        for page in (admin, front): page.on('pageerror', lambda e: errors.append(str(e)))
        front.clock.install()
        front.goto(BASE + '/pricing')
        monthly = front.locator('article').filter(has=front.get_by_role('heading', name='Pro 月卡', exact=True))
        expect(monthly.locator('strong').first).to_have_text('19.9')
        admin.goto(BASE + '/admin/pricing')
        expect(admin.get_by_role('heading', name='会员价格管理', exact=True)).to_be_visible()
        if width < 1024: admin.get_by_role('button', name='打开导航菜单').click()
        expect(admin.get_by_role('link', name='会员价格', exact=True)).to_be_visible()
        if width < 1024: admin.get_by_role('button', name='关闭导航菜单').click()
        admin.get_by_role('button', name='修改月卡价格', exact=True).click()
        dialog = admin.locator('dialog[open]')
        dialog.get_by_label('新价格（元）').fill('19.999')
        dialog.get_by_role('button', name='下一步，确认价格').click()
        expect(dialog.get_by_role('alert')).to_be_visible()
        dialog.get_by_label('新价格（元）').fill('29.90')
        dialog.get_by_role('button', name='下一步，确认价格').click()
        expect(dialog).to_contain_text('原价：¥19.90')
        expect(dialog).to_contain_text('新价：¥29.90')
        assert not state['saves']
        dialog.get_by_role('button', name='确认保存价格').click()
        expect(dialog).to_be_hidden()
        assert state['saves'] == [dict(price_cents=2990, revision=1)]
        front.clock.fast_forward(30000)
        expect(monthly.locator('strong').first).to_have_text('29.9')
        state['plans'][1].update(price_cents=3090, revision=3)
        front.evaluate("window.dispatchEvent(new Event('focus'))")
        expect(monthly.locator('strong').first).to_have_text('30.9')
        admin.screenshot(path=str(SHOTS / f'prices-{width}.png'), full_page=True)
        # Another administrator changes the yearly price before saving this form.
        admin.get_by_role('button', name='修改年卡价格').click()
        dialog.get_by_label('新价格（元）').fill('109.00')
        dialog.get_by_role('button', name='下一步，确认价格').click()
        state['conflict'] = True
        dialog.get_by_role('button', name='确认保存价格').click()
        expect(admin.get_by_role('alert')).to_contain_text('套餐已被修改')
        assert len(state['saves']) == 1
        # Open the modal with current pricing, then change it before submitting.
        state['plans'][1].update(price_cents=3190, revision=4)
        monthly.get_by_role('button', name='开通月卡', exact=True).click()
        pay = front.locator('dialog[open]')
        expect(pay).to_contain_text('¥31.90')
        state['plans'][1].update(price_cents=3990, revision=5)
        pay.get_by_role('button', name='前往支付宝付款').click()
        expect(pay.get_by_role('alert')).to_contain_text('套餐价格已更新')
        expect(pay).to_contain_text('¥39.90')
        assert front.evaluate('window.cashierSubmits.length') == 0
        pay.get_by_role('button', name='前往支付宝付款').click()
        front.wait_for_function('window.cashierSubmits.length === 1')
        assert state['orders'][-1]['expected_price_cents'] == 3990
        assert state['orders'][-1]['expected_revision'] == 5
        # Read-only operators can access the page but receive no modify controls.
        state['role'] = 'admin'
        admin.reload()
        expect(admin.get_by_text('当前账号可查看价格，仅超级管理员可以修改。')).to_be_visible()
        expect(admin.get_by_role('button', name='修改月卡价格')).to_have_count(0)
        front.goto(BASE + '/')
        reads = state['plan_reads']
        front.clock.fast_forward(60000)
        assert state['plan_reads'] == reads
        for page in (front, admin):
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        context.close()
        print(f'PASS admin pricing / sync / checkout at {width}px')
    browser.close()
