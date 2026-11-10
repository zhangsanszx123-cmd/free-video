# 用户账号扩展方案（已确认并实现）

日期：2026-11-10。状态：用户已确认，v1.5 已实现。最终行为以 [requirements.md](./requirements.md) v1.5 与 [design.md](./design.md) 第 0 节为准，验收见 [account-verification.md](./account-verification.md)。

## 用户确认的决策

| 问题 | 结论 |
|---|---|
| 账号方式 | 用户名 + 密码；无邮箱/短信、找回密码、第三方登录 |
| 存储 | MySQL 8.x（草案中的 SQLite 改为 MySQL），PyMySQL 1.2.3，原生 SQL；root 直连本机 |
| 建库建表 | 提供 `backend/sql/schema.sql`；应用启动自动 `CREATE TABLE IF NOT EXISTS` |
| 测试库 | 独立 `freevideo_test`，测试清空表；未配置则跳过账号测试 |
| 游客权限 | 部分功能需登录：批量提取、AI 总结/追问/导图（含 `/ai` 翻译）；前后端都拦截 |
| 任务归属 | 本次不改，继续匿名会话；下载历史留待后续 |
| 个人中心 | 资料 + 改昵称、修改密码、登录设备管理、注销账号 |
| 登录/注册形式（验收后变更） | 单个弹窗内 Tab 切换；需登录入口留在当前页弹窗，成功后进入目标页；`/login`、`/register` 保留为备用页；改密/过期后回首页弹窗，注销后仅提示 |

## 实施记录

1. 后端：`account_store.py` / `account_auth.py` / `account_api.py`、`errors.AccountError`、`config` 新增 MySQL 与限速配置、`main.py` 注册路由与拦截。
2. 前端：`account.js`、登录/注册弹窗 `AuthModal`（共用 `LoginForm`/`RegisterForm`，备用页保留）、个人中心页面、`AuthShell` / `FormField` / `UserAvatar`、NavBar 账号入口、路由守卫、首页 AI Tab 登录引导、跨标签页同步与身份切换清理。
3. 测试：`tests/test_accounts.py`（39 项，真实 MySQL）、`frontend/tests/account_ui.py`（7 项浏览器全流程），原有用例通过 `dependency_overrides` 以登录身份运行。

## 后续可选

- 生产改用仅有 `freevideo` 库权限的专用 MySQL 账号、HTTPS + `SESSION_SECURE=true`。
- 下载历史 / 任务归属账号（B2）、找回密码（需邮件服务）、真实付费与额度（B3）。
- 多进程部署时把限速迁到共享存储，数据库连接改为连接池。
