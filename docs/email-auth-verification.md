# 邮箱账号验证记录

日期：2026-11-15。最终规则见 [邮箱账号方案](./email-auth-plan.md)。

**本记录为最初免邮箱验证阶段。后续已启用 163 邮件链接验证，最新结果与本机验收见 [邮箱验证指南](./email-verification-setup.md)。**

## 自动验证

| 检查 | 结果 |
|---|---|
| 后端 `pytest backend/tests -m 'not network' -q` | 260 通过，4 个网络测试排除；1 条既有 oss2 utcnow 弃用警告 |
| 最终账号专项 `pytest backend/tests/test_accounts.py backend/tests/test_email_captcha.py -q` | 55 通过；含新增验证状态拦截和迁移幂等测试 |
| `npm run build` | 通过 |
| `email_auth_ui.py` | 1440px / 390px 通过，截图已检查；格式错误、换图、错误码刷新、注册自动登录及独立页登录 |
| `task_recovery_ui.py` | 10 通过；弹窗内部点击、关闭、离页与原操作恢复 |
| `ui_regression.py` | 22 通过 |
| `account_ui.py` | 独立测试库、真实后端 :8014，9 项全部通过；覆盖改密、设备、注销、跨标签同步、失效后重新登录与返回原页 |
| `git diff --check` / Python 编译 | 通过（Git 提示文档换行将按仓库规则转 CRLF） |

完整回归通过后增加验证状态与迁移测试，并调整密码错误文案，再执行最终 55 项专项；未重复执行已通过且未受这些改动影响的下载测试。

## 本机可验收状态

- 已重启本机 :8000 业务服务加载新代码，前端 dist 已重新构建。
- 实测 `/api/auth/captcha` 返回 200、有效 PNG 数据；省略验证码直接注册返回 422。
- 启动迁移后核验业务库 `freevideo`：users=0、payment_orders=0、payment_events=0。浏览器自动化只在 `freevideo_test` 建号。
- 测试截图：`.runtime/email-auth-ui/`；测试输出：`.runtime/email-pytest-final.txt`、`email-final-focused.txt`、`email-account-ui-passed.txt`、`email-ui-regression.txt`、`email-recovery-ui.txt`。

## 人工验收

打开本机网站，刷新后按方案中的六步操作验收。无需配置邮件服务。当前邮箱默认通过验证，只校验格式；邮件发送和链接验证仍为未来扩展，不能把当前状态理解为已确认邮箱所有权。
