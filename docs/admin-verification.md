# 管理后台首版验证记录

日期：2026-11-16。范围经用户确认，见 [首版方案](./admin-management-plan.md)。

状态：功能实现、自动化验证、业务库增量迁移和后端重新加载完成，等待用户初始化首位超级管理员密码并人工验收。用户随后要求将实现、测试和文档提交 Git；提交不代表人工验收通过。

## 已交付

- 独立后台登录、退出、本人修改密码、路由守卫、后台 404 和身份查询故障重试。
- 注册用户搜索、筛选、分页、详情、禁用/启用；普通管理员和超级管理员均可操作。
- 超级管理员管理后台账号：新增、编辑显示名/角色/状态、重置密码；最后有效超级管理员保护。
- 前后台身份隔离；禁用、角色变化或重置密码撤销对应会话；旧请求不得清除新会话。
- 本机隐藏输入初始化和密码恢复，管理写操作审计，无默认密码和公开后台注册。

## 验证结果

| 检查 | 最终结果与边界 |
|---|---|
| 后端全量非网络 pytest | **316 passed，4 network deselected**，使用 `freevideo_admin_test`；含 38 项后台权限、并发、迁移、邮件、CLI 等场景。存在一条既有 oss2 弃用警告。 |
| `admin_ui.py` | **7 项通过**，API 全部模拟；覆盖两级权限、启停、详情、账号新增/编辑/重置、自改密、后台身份刷新 503 后重试、角色变化和 404。 |
| `admin_real_ui.py` | **3 项通过**，真实 FastAPI + 独立 MySQL `freevideo_admin_ui_test`；用户启停、前后台 Cookie 隔离、会员资料保留、管理员新增编辑/启停撤销会话/重置密码及手机布局。 |
| `admin_races.mjs` | BroadcastChannel **9/9**、storage **9/9**；覆盖前后台隔离、同账号/跨账号重登、迟到 401 和 me、角色变化与安全回跳。 |
| 原有 `ui_regression.py` | 最终完整运行 **22 项通过**。 |
| `task_recovery_ui.py` | **11 项通过**。 |
| `frontend_followup_ui.py` | **4 项通过**，保留前一批分享链接、会话及 B站分 P 修复。 |
| `email_auth_ui.py` | 1440×768、1024×600、390×844 三种窗口通过。 |
| 原有 Node 检查 | `account_races.mjs` 两组、`auth_request_races.mjs` 两通道各 56 项、`bilibili_embed.mjs` 5 项通过。 |
| 前端构建 | `npm run build` 通过，86 modules；生产 dist 已更新。 |
| 桌面/手机 | 1440/390 截图已目视检查；筛选框宽度至少 100px、标签不逐字换行、无横向溢出，页面无 JS 错误。 |
| 当前业务服务冒烟 | `/api/admin/auth/me` 为 `{admin:null}` 且禁止缓存；游客管理接口 401；后台登录页可见。月卡仍为 50 分、真实支付启用、模拟收银台 404。 |
| 静态复核 | 独立复核完成，`git diff --check` 通过。 |

后台与原有浏览器 unittest 共 47 项通过（7+3+22+11+4），邮箱按三种窗口另记。测试账号和初始化密码只用于独立测试库；没有将测试后台账号复制到业务库。

## 测试中修复的问题

1. ASCII 邮箱或后台登录名列与中文昵称搜索组合时触发 MySQL 排序规则冲突；字段转换为 utf8mb4 后，中文、邮箱、登录名和 ID 查询回归通过。
2. 手机搜索栏挤压筛选项，标签竖排且下拉框过窄；调整为整行搜索和两列筛选，并增加尺寸断言。
3. 后台跨标签身份刷新遇到临时 503 后原来停留在返回登录占位；改为错误卡和独立重试锁，保留原页面筛选，恢复后继续访问，不影响前台身份。
4. 修改密码退出时后台布局短暂重挂可能覆盖成功提示；受保护后台视图随身份状态切换，避免旧布局继续请求。

另有两处测试假设已修正：数字 ID 搜索也允许匹配邮箱/登录名中的数字；登录回跳应保留筛选条件，不能要求固定 URL 编码字符串。原页面回归曾在并行开发热更新期间出现一次批量按钮定位超时，代码稳定后最终完整 22 项通过。

## 环境与数据

- 后端测试仅使用 `freevideo_admin_test`，浏览器真实联调另用 `freevideo_admin_ui_test:8015`；未与业务库或共享测试库并行清空数据。
- 测试进程的 SMTP、ZPAY、AI、ASR 凭证均清空，后台支付对账关闭，没有发送真实邮件、付款或收费识别。
- 业务库只执行增量建表/加列/guard 初始化，前后核对账号基础信息、会员、支付订单和套餐配置保持一致；现有注册用户默认启用，月卡价格仍为 0.50 元。
- 加载更新前核查无活动识别记录及近期待支付新单，后端已重新启动于原 `:8000`，真实支付配置保留。没有自动初始化业务后台密码、重置用户密码或修改会员状态。
- 模拟截图在 `.runtime/admin-ui/`，真实测试库截图在 `.runtime/admin-live-ui/`，均为测试数据。

## 重跑

从 backend 目录运行后端测试，测试库会清空测试账号，不与使用同库的浏览器服务并行：

```powershell
$env:MYSQL_TEST_DATABASE='freevideo_admin_test'
.venv/Scripts/python -m pytest
```

Vite `:5178` 启动后，从仓库根目录运行模拟 UI 和 Node 检查：

```powershell
python -P frontend/tests/admin_ui.py -v
node frontend/tests/admin_races.mjs
node frontend/tests/admin_races.mjs --storage
```

构建前端后，另开终端启动隔离的真实测试后端，再运行浏览器检查：

```powershell
backend/.venv/Scripts/python -P frontend/tests/admin_test_server.py
```

```powershell
python -P frontend/tests/admin_real_ui.py -v
```

真实测试后端每次启动都会清理和重新填充 `freevideo_admin_ui_test`，不要指向业务库；固定测试密码不会用于生产初始化。

人工验收按 [后台指南](./admin-setup.md) 执行，先在本机为 `admin` 设置密码，再打开 `http://localhost:8000/admin/login`。
