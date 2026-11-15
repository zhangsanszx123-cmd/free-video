# 前端审查与优化验证记录

日期：2026-11-15。范围与决策见 [requirements.md](./requirements.md) 顶部「前端审查与优化」。

交付状态：已实现并通过自动化验证，等待用户人工验收。

## 审查结论（修复前）

两种宽度（1440 / 390）下全部页面无横向溢出、无 JS 报错、弹窗焦点循环与 Esc 正常。已修复的问题：

| 编号 | 问题 | 处理 |
|---|---|---|
| A1-A5 | FAQ、「限时免费」、8K/广告/无水印、付费/按量计费/API 预算/写死 60 分钟、页脚重复链接 | 文案对齐真实规则，页脚指向真实页面 |
| 角标 | PRO 角标与现行规则（登录 + 月度识别额度）不符 | 全部去掉，页顶改为「登录后使用」 |
| B1 | `/ai` 复制被拒产生未捕获异常（已复现） | try/catch + 提示 |
| B2 | `/ai` 总结无提交锁/卸载保护，Tab 缺 aria | 加锁、AbortController、aria |
| B3 | 手机菜单 Esc 不关闭（已复现） | Esc 与点击外部关闭，焦点返回 |
| B4 | 桌面账号下拉「个人中心」重复（已复现） | 删除重复项 |
| B5 | 结果卡重复下载/复制按钮 | 保留头部下载与卡内「复制链接」 |
| B6 | 仅封面显示为「图片内容」 | 「封面图片」 |
| B7 | 无音频预览时的空播放器 | 提示文字 |
| B8 | iframe 控制台警告 | 去掉 `allowfullscreen` |
| B9 | 未知路由静默回首页 | 404 页 |
| B10 | 手机占位符截断/选项卡两行/缺 aria | 缩短占位符、选项卡同行、补 aria |
| D1/D2 | 个人中心默认分区与说明位置；历史页背景 | 默认「会员与额度」；`hero-bg` |

未做：C 组手机触控区（用户未选择）；结果卡内占位入口（用户要求保持）。

## 自动化验证（最终结果）

- `cd frontend && npm run build`：成功。
- `cd backend && .venv/Scripts/python -m pytest`：222 passed，4 项网络测试 deselected。
- `python -P frontend/tests/ui_regression.py`（Vite :5178，全 mock）：13 项通过。
- `python -P frontend/tests/batch_subtitles_ui.py`：3 项通过。
- `python -P frontend/tests/account_ui.py`（真实后端 :8010 + `freevideo_test`）：9 项通过。
- `python -P frontend/tests/membership_ui.py`：6 项通过；注意 :8010 后端需设 `ZPAY_PID=`、`ZPAY_KEY=` 为空，否则 `.env` 里的真实支付配置会让「在线支付暂未开放」断言失败（与本次改动无关）。
- `python -P frontend/tests/payment_ui.py`（:8011 + `ZPAY_MOCK=true`）：3 项通过。
- 开发中的发现：手机菜单「点击外部关闭」最初用 `contains(event.target)`，被 `account_ui` 的手机用例发现会误关菜单，已改用 `composedPath()`，并在 `ui_regression.py` 加入开启后保持可见的断言。

## 人工验收

1. 桌面与手机查看首页：无 PRO 角标；统计区为「4K+ 原画画质 / 免安装」；手机上两个模式选项卡同行，占位符不截断。
2. 解析一个视频：只有一个「下载高清视频」，卡片内只有「复制链接」；封面显示在「封面图片」。
3. 打开账号下拉：只有一个「个人中心」入口；按 Esc 关闭且焦点回到头像按钮；手机菜单 Esc/点空白处可关闭。
4. `/batch`、`/ai`、`/learn`：页顶为「登录后使用」，说明里为「消耗你的每月语音识别额度」。
5. 访问 `/abc`：显示 404 页。个人中心默认显示「会员与额度」，`/history` 背景与其它页一致。
6. FAQ「AI 总结是怎么实现的？」描述了无字幕时的语音识别。

真实平台解析、下载与云端 AI/ASR 输出质量不在模拟浏览器回归覆盖范围内。

## 套餐使用上限（2026-11-15）

- 后端 `pytest`：232 passed（新增 `test_limits.py` 10 项）；`test_transcriptions` 的超长音频用例改为引用 `config.ASR_MAX_DURATION + 1`。
- `ui_regression.py`：16 项通过（新增定价/额度卡、批量超限、AI 超限提示）；`batch_subtitles_ui.py` 3、`account_ui.py` 9、`membership_ui.py` 6 项通过。
- 主库 `freevideo` 在重启后自动迁移：`/api/plans` 返回 免费 10/3/8/1、月卡 300/10/30/10、年卡 500/15/60/20（按 AI 视频/批量条数/识别分钟/追问每天，用户最终指定）。
- 人工验收：个人中心「会员与额度」应看到 AI 视频/追问/批量/识别时长四项；定价页套餐卡与对比表有新增行；`/batch` 提交超过 3 条应在前端被拦截并提示升级；用测试账号把 `ai_monthly_limit` 调小后（`python -m app.membership configure free --price-cents 0 --monthly-seconds 1800 --ai-monthly-limit 2`）连续总结 3 个不同视频，第 3 个应提示次数已用完，重复总结同一视频不受影响。

## 游客限制（2026-11-15）

- 后端 `pytest`：240 passed（新增 `test_guest.py` 8 项，`test_membership` 中 1 项按新规则改写）。
- `ui_regression.py` 18 项、`batch_subtitles_ui.py` 3、`account_ui.py` 9、`membership_ui.py` 6、`payment_ui.py` 3 项通过。
- 人工验收：用无痕窗口访问站点，解析并下载第 1、2 个链接正常，同一链接重复不扣次；解析第 3 个链接应弹出登录窗并提示名额用完；游客结果卡的字幕/文稿区只显示登录提示；清 Cookie 后同一网络仍受限。注册新账号后应看到「游客期间下载的视频时长约 N 分钟，已计入本月语音识别额度」，个人中心「已用」相应增加。
