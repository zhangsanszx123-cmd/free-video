# 登录提示验证与验收

日期：2026-11-17。用户已确认并要求直接修改，实现完成，待人工验收。

- 未注册邮箱：显示「该邮箱尚未注册，请先注册」和「立即注册」按钮。
- 已注册邮箱密码错误：显示「密码错误」。两类失败均沿用原有邮箱与 IP 限流。
- 点击立即注册或底部免费注册，注册表单带入邮箱、密码留空；弹窗续作与备用页面 redirect 保留。

验证结果：

- 后端离线测试 164 passed、4 network deselected。排除 accounts、membership、payments、limits、guest、admin 六个数据库模块；新增独立 mock 用例覆盖两类错误及各自第 6 次锁定，不接业务数据库。
- `python -P frontend/tests/login_feedback_ui.py`：1440px / 390px × 弹窗 / 备用页四个场景通过，覆盖密码错误、未注册提示、注册邮箱带入、空密码、验证码、redirect、无横向溢出及无页面 JS 错误。API 全部模拟。
- `npm run build` 通过；已有真实账号 UI 与数据库账号测试的旧文案断言已更新，本轮未运行这些数据库用例。
- 本地 :8000 后端已重启，健康检查正常；前端 dist 已更新。没有执行真实注册、发邮件、付费识别或支付。

人工验收：刷新 http://localhost:8000，使用未注册邮箱尝试登录，确认提示与立即注册按钮；点击后检查邮箱保留、密码为空。另用已注册邮箱输入错误密码，确认显示「密码错误」。

复跑后端（backend 目录）：

```powershell
.venv/Scripts/python -m pytest --ignore=tests/test_accounts.py --ignore=tests/test_membership.py --ignore=tests/test_payments.py --ignore=tests/test_limits.py --ignore=tests/test_guest.py --ignore=tests/test_admin.py -q
```

浏览器脚本默认访问本地 :8000 已构建页面，服务须已启动。
