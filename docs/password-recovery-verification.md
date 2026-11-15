# 找回密码验证与验收

日期：2026-11-15。

## 使用

1. 在账号弹窗第三个「找回密码」选项卡，或点击登录表单的「忘记密码？」，输入注册邮箱。无需离开当前页面。
2. 查收「重置你的 FreeVideo 登录密码」，在运行网站的电脑打开邮件链接。
3. 输入一个新密码（8–128 字符），点击「重置密码」。不需要原密码，不自动登录。
4. 返回登录页使用新密码登录；原密码失效、所有旧登录设备被撤销。

链接 30 分钟有效、只能使用一次。重新申请须间隔 60 秒，新链接替代旧链接。更改密码后，之前发出的找回链接也失效。未知邮箱和发信失败统一提示，未收到可检查垃圾邮件并稍后重试；服务端不自动重发。

待验证账号的邮箱所有者也可用此流程完成邮箱验证，注册日从成功重置时起算；不会删除会员、额度或订单。

## 验证结果

- 后端非网络完整回归：276 项通过，4 个网络测试排除；保留 1 条既有 oss2 弃用警告。
- 覆盖全设备会话撤销、新旧密码、弱密码、过期、重放、并发、同邮箱冷却、未知邮箱统一响应、改密使旧链接失效、跨站来源和待验证账号恢复。
- `password_recovery_ui.py`：1440px 和 390px 检查通过，含登录弹窗入口、邮箱格式、申请提示、hash 清除、显式重置与缺少凭证禁用。
- `email_link_real_ui.py`：真实后端 + 独立测试库，仅替换 SMTP，桌面及手机注册激活和找回密码完整流程通过。未给真实用户发送测试重置邮件。
- 前端构建通过；原注册/登录布局检查通过。截图 `.runtime/password-recovery-ui/`，后端日志 `.runtime/password-reset-pytest.txt`。
- 弹窗调整后重新通过桌面/手机发信、选项卡顺序与返回登录检查，以及三种窗口注册登录布局检查；本次仅重构前端共用表单，后端接口不变。

本机仍复用 `.env` 的 163 SMTP 和 `PUBLIC_BASE_URL=http://localhost:8000`，授权码不进入代码或前端。正式部署需使用可访问的 HTTPS 地址。

## 重跑命令（仓库根目录，PowerShell）

```powershell
backend/.venv/Scripts/python -m pytest backend/tests -m 'not network' -q
```

Mock 界面检查需要先启动 Vite :5178，然后使用已有 Playwright 的系统 Python：

```powershell
python -P frontend/tests/email_auth_ui.py
python -P frontend/tests/email_verification_ui.py
python -P frontend/tests/password_recovery_ui.py
python -P frontend/tests/task_recovery_ui.py
```

真实账号邮件流程在两个终端分别运行，SMTP 被私有本地发件箱替换，测试数据仅写入 freevideo_test；不要与清空同一测试库的 pytest 同时运行：

```powershell
backend/.venv/Scripts/python -P frontend/tests/email_link_test_server.py
```

```powershell
python -P frontend/tests/email_link_real_ui.py
```

原 `account_ui.py` 测试自动登录、资料和设备管理，启动其后端时需显式 `AUTH_EMAIL_VERIFICATION_REQUIRED=false`，避免真实发信；邮件验证和密码恢复由上面的独立流程覆盖。
