# 前端交互修复验证与验收

日期：2026-11-16。用户确认范围：本轮方案中的 A1、A2、A3。

交付状态：实现、自动化验证和文档同步完成，待用户人工验收。

## 变更结果

| 编号 | 修复前 | 当前行为 |
|---|---|---|
| A1 | 旧请求迟到的登录失效响应注销新登录身份，包括同账号重新登录。 | 五类请求入口绑定发起时的会话版本；旧错误仅返回原调用方，当前会话真实失效仍正常登出。普通 me/昵称更新不变更会话版本；跨标签会话通知立即废弃旧错误。 |
| A2 | 首页 AI 分享链接在等待登录状态时，迟到初始化覆盖新输入、清空或下载模式。 | 初始化先复核操作版本与组件状态，用户后续操作优先。正常分享仍自动解析；游客 AI 分享继续降级为下载，不主动打开登录窗。 |
| A3 | 首页与工作台的 B站 iframe 遗漏选集，可能与所选分 P 文稿不对应。 | 两入口共用播放器构造工具，初始与跳播均保留 `p`；缺省或非法值回第 1 P。 |

没有修改后端接口、数据库、套餐或付费识别规则。此前列出的空 AI 输出、下载保留期、支付对账和测试说明候选未纳入本批。

## 修复前复现

- A1：新增会话回归首版 46 项中 26 项失败，实际观察到旧 401 清除新身份；随后扩展覆盖并完成修复。
- A2：新增浏览器用例在两种宽度、游客和已登录状态下，编辑、清空、切下载共 12 个子场景失败，输入均被分享链接覆盖。离页保护已有部分有效行为。
- A3：组件级回归先出现 4 项失败，iframe 的 `p` 实际为 null。

## 最终验证

| 检查 | 结果 |
|---|---|
| `account_races.mjs` | 原有身份查询竞态与强制刷新两组检查通过。 |
| `auth_request_races.mjs` | BroadcastChannel 56/56，storage 备用通道 56/56。覆盖五个请求入口、跨账号/同账号重登、注册/验证登录、读取错误正文时切会话、当前失效、普通刷新和跨标签消息。 |
| `bilibili_embed.mjs` | 5 项通过。覆盖两组件实际 setup/seek、默认/P2/P3、非法值、查询顺序、连续跳播及原平台时间链接。 |
| `frontend_followup_ui.py` | 4 项通过，包含桌面/390px 的 29 个子场景：16 个用户打断初始化场景、4 个正常分享场景、8 个分 P 预览/跳播场景，以及旧 401 后新登录身份保持场景。 |
| `ui_regression.py` | 22 项通过。 |
| `task_recovery_ui.py` | 11 项通过。 |
| `batch_subtitles_ui.py` | 3 项通过，含恢复、导出及 ZIP 失败重试。 |
| `email_auth_ui.py` | 1440×768、1024×600、390×844 三种窗口通过，含注册待验证及登录成功。 |
| 前端构建 | `npm run build` 通过，75 modules。 |
| 桌面/手机截图 | 首页 AI 结果与时间戳跳播的 1440px/390px 模拟截图已检查，两种宽度均无横向溢出、无页面 JS 错误。 |
| 静态复核 | 独立代码复核完成，`git diff --check` 通过。 |

浏览器 unittest 合计 40 项通过；邮箱界面按三种窗口单独记录，不混算测试数量。以上均使用模拟 API/播放器；未调用真实 SMTP、支付、平台下载、AI 或 ASR，没有运行清空共用测试库的数据用例。

分析阶段的 162 项后端离线基线结果保留在 [方案](./frontend-next-iteration-plan.md) 中；本批只改前端，没有将该基线写作本轮重新执行的后端结果。

本地截图位于 `.runtime/frontend-followup-20261116/home-ai-1440.png` 和 `home-ai-390.png`，为模拟数据与播放器，不能证明真实平台播放效果。

## 复跑方式

从仓库根目录执行 Node 检查：

```powershell
node frontend/tests/account_races.mjs
node frontend/tests/auth_request_races.mjs
node frontend/tests/auth_request_races.mjs --storage
node frontend/tests/bilibili_embed.mjs
```

先在 frontend 启动 `npm run dev -- --host 127.0.0.1 --port 5178 --strictPort`，再从仓库根目录运行：

```powershell
$env:PYTHONIOENCODING='utf-8'
python -P frontend/tests/frontend_followup_ui.py -v
python -P frontend/tests/ui_regression.py -v
python -P frontend/tests/task_recovery_ui.py -v
python -P frontend/tests/batch_subtitles_ui.py -v
python -P frontend/tests/email_auth_ui.py
```

构建仍在 frontend 目录运行 `npm run build`。

## 人工验收

1. 刷新站点，两个标签页分别操作登录、退出或切换账号，确认最新登录身份稳定；正常登录过期时仍会提示重新登录。精确的迟到 401 与同账号重登交错由自动化覆盖。
2. 在慢网下打开首页 AI 分享链接（`/?view=ai&url=<编码后的视频链接>`），身份检查返回前修改链接、清空、切回下载或离页，确认旧链接不会恢复或提交。再正常打开分享链接，确认已登录时进入 AI，游客时进入下载。
3. 任选确有第 2/3 P 的 B站公开视频，带 `?p=2` 或 `?p=3` 分别在首页与学习工作台打开，确认实际播放器对应选集；点击总结时间戳后仍停留在该 P 并跳到对应位置。真实嵌入播放器还受平台网络与播放限制影响，模拟验证不代替此项。
4. 在手机上重复分享链接与分 P 操作，检查输入、模式、预览和总结操作正常。

生产前端构建已生成于 `frontend/dist`；现有后端托管 dist 时刷新即可加载本批前端。没有自动重启常驻后端或发布远程环境。用户随后要求将本批实现、方案和验收记录提交 Git；提交不代表人工验收已经通过。
