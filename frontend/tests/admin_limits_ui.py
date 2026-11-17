"""Quota editor visual/interaction checks on built :8000, all APIs mocked."""
from pathlib import Path
from copy import deepcopy
from playwright.sync_api import sync_playwright, expect

SHOTS = Path('.runtime/admin-limits-ui')
SHOTS.mkdir(parents=True, exist_ok=True)
PLANS = [dict(code=code, name=name, monthly_seconds=seconds, revision=1, price_cents=price, months=months,
              ai_monthly_limit=ai, chat_daily_limit=chat, batch_max_links=batch, asr_max_minutes=asr)
         for code, name, seconds, price, months, ai, chat, batch, asr in [
             ('free', '免费用户', 1800, 0, 0, 10, 1, 3, 8),
             ('monthly', '月卡会员', 36000, 1990, 1, 300, 10, 10, 30),
             ('yearly', '年卡会员', 108000, 9900, 12, 500, 20, 15, 60)]]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 1024, 390):
        state = dict(plans=deepcopy(PLANS), role='superadmin', writes=[], conflict=False)
        errors = []
        context = browser.new_context(viewport=dict(width=width, height=900))

        def api(route):
            path = route.request.url.split('/api/')[1].split('?')[0]
            if path == 'admin/auth/me':
                return route.fulfill(json={'admin': dict(id=1, username='owner', nickname='管理员', role=state['role'], status='active')})
            if path == 'auth/me':
                return route.fulfill(json={'user': dict(id=2, email='user@example.com', nickname='用户')})
            if path == 'auth/sessions': return route.fulfill(json={'sessions': []})
            if path == 'pay/orders': return route.fulfill(json={'orders': []})
            if path == 'admin/plan-limits':
                return route.fulfill(json={'plans': state['plans'], 'ceilings': dict(batch_max_links=20, asr_max_minutes=60)})
            if path.startswith('admin/plan-limits/'):
                body = route.request.post_data_json
                if state['conflict']:
                    return route.fulfill(status=409, json=dict(code='ADMIN_PLAN_CONFLICT', detail='套餐已被修改，请刷新后重新确认'))
                state['writes'].append(body)
                plan = next(p for p in state['plans'] if p['code'] == path.split('/')[-1])
                plan.update({k: v for k, v in body.items() if k != 'monthly_minutes'})
                plan.update(monthly_seconds=body['monthly_minutes'] * 60, revision=body['revision'] + 1)
                return route.fulfill(json={'plan': plan})
            if path == 'plans': return route.fulfill(json=dict(plans=state['plans'], payment_enabled=True))
            if path == 'account/membership':
                return route.fulfill(json=dict(plan='monthly', name='月卡会员', limit_seconds=state['plans'][1]['monthly_seconds'], available_seconds=1000, used_seconds=200, reserved_seconds=100))
            return route.fulfill(json=dict(ok=True, plans=[]))

        context.route('**/api/**', api)
        page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:8000/admin/limits')
        expect(page.get_by_role('heading', name='套餐额度管理', exact=True)).to_be_visible()
        if width < 1024: page.get_by_role('button', name='打开导航菜单').click()
        expect(page.get_by_role('link', name='套餐额度', exact=True)).to_be_visible()
        if width < 1024: page.get_by_role('button', name='关闭导航菜单').click()
        if width < 768: page.get_by_role('button', name='月卡会员', exact=True).click()
        page.screenshot(path=str(SHOTS / f'overview-{width}.png'), full_page=True)
        page.get_by_role('button', name='编辑月卡额度', exact=True).click()
        dialog = page.locator('dialog[open]')
        assert dialog.evaluate('el => el.getBoundingClientRect().top >= 0 && el.getBoundingClientRect().bottom <= innerHeight')
        page.screenshot(path=str(SHOTS / f'editor-{width}.png'))
        dialog.get_by_label('视频转文字时长').fill('1200')
        dialog.get_by_label('AI 视频总结').fill('200')
        dialog.get_by_label('批量提取').fill('21')
        dialog.get_by_role('button', name='核对 3 项修改').click()
        expect(dialog.get_by_text('请输入 1–20 的整数', exact=True)).to_be_visible()
        assert not state['writes']
        dialog.get_by_label('批量提取').fill('10')
        dialog.get_by_role('button', name='核对 2 项修改').click()
        expect(dialog).to_contain_text('本次修改 2 项额度')
        expect(dialog).to_contain_text('已有用户')
        page.screenshot(path=str(SHOTS / f'confirm-{width}.png'))
        dialog.get_by_role('button', name='确认保存并立即生效').click()
        expect(dialog).to_be_hidden()
        assert len(state['writes']) == 1
        assert state['writes'][0]['monthly_minutes'] == 1200
        expect(page.get_by_role('status')).to_contain_text('额度已更新')
        # A stale form cannot overwrite a newer edit.
        page.get_by_role('button', name='编辑月卡额度', exact=True).click()
        dialog.get_by_label('视频转文字时长').fill('600')
        dialog.get_by_role('button', name='核对 1 项修改').click()
        state['conflict'] = True
        dialog.get_by_role('button', name='确认保存并立即生效').click()
        expect(page.get_by_role('alert')).to_contain_text('套餐已被修改')
        # Frontend sees the updated values; personal quota also refreshes in place.
        front = context.new_page(); front.on('pageerror', lambda e: errors.append(str(e)))
        front.clock.install()
        front.goto('http://127.0.0.1:8000/pricing')
        monthly = front.locator('article').filter(has=front.get_by_role('heading', name='Pro 月卡', exact=True))
        expect(monthly).to_contain_text('20小时')
        expect(monthly).to_contain_text('每月 200 个视频')
        front.goto('http://127.0.0.1:8000/account')
        quota = front.get_by_role('region', name='语音识别额度')
        expect(quota).to_contain_text('20小时')
        state['plans'][1]['monthly_seconds'] = 36000
        front.clock.fast_forward(30000)
        expect(quota).to_contain_text('10小时')
        state['role'] = 'admin'; page.reload()
        expect(page.get_by_text('当前为只读模式，只有超级管理员可以修改额度。')).to_be_visible()
        expect(page.get_by_role('button', name='编辑月卡额度', exact=True)).to_have_count(0)
        for surface in (page, front): assert surface.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        context.close()
        print(f'PASS quota editor and sync at {width}px')
    browser.close()
