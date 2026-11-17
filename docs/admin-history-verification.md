# 后台提取记录验证

日期：2026-11-17。用户要求简化，直接复用前台历史记录，不新增数据库字段；最终以用户邮箱展示记录归属。

后续用户指定展示用户邮箱，替代用户 ID。后台查询关联现有 users.email，返回 user_email；没有新增数据库字段，桌面/手机/详情均显示邮箱并支持长邮箱换行。后台历史数据库专项 1 passed、52 deselected，邮箱浏览器两种宽度和前端构建通过；前台账号历史响应保持原样，不返回额外邮箱。

## 实现范围

- 后台导航「提取记录」与 `/admin/history`，普通/超级管理员可只读查看。
- 复用 transcription_records，按现有 user_id 关联 users.email，后台列表和详情显示用户邮箱；搜索标题/文稿、筛选执行中/成功/失败，20 条分页。前台响应字段保持原样，不增加邮箱。
- 与前台一致仅展示未隐藏、未过期的字幕/转写任务，沿用 30 天清理。没有新增 schema、日志采集、下载/解析记录或游客记录。
- 桌面表格、手机卡片；详情显示现有错误/文稿，Vue 文本转义，原视频链接过滤协议。没有删除或导出入口。

## 验证

- 独立数据库 freevideo_history_admin_test 的后台历史及既有历史专项 4 passed，74 deselected；覆盖跨用户汇总、普通管理员查看、游客/前台会话拒绝访问、隐藏与过期排除、搜索、状态、稳定分页、前台归属隔离及 no-store。
- admin_history_ui.py：1440px/390px 两个完整场景通过；模拟全部 API，覆盖分页、筛选、搜索、重试、空列表、普通管理员、文稿 HTML 转义、不安全链接拦截、无横向溢出和 JS 错误。
- 新增浏览器截图位于 .runtime/admin-history-ui/history-1440.png 和 history-390.png，全部为模拟数据。
- 既有 membership 与 API 模块 38 passed；后台 UI 7 项、前台 UI 22 项通过。前端构建与 git diff --check 通过。
- :8000 已重启加载新接口，健康检查正常，后台页面 HTTP 200；未登录访问历史 API 返回 401。手机截图已检查。

没有修改业务数据或历史保留策略，没有真实下载、发信、AI/ASR 或支付调用。本批实现、测试与文档按用户要求一并纳入 Git，人工验收仍待用户完成。

## 复跑与验收

后台专项在 backend 目录：

```powershell
$env:MYSQL_TEST_DATABASE='freevideo_history_admin_test'
.venv/Scripts/python -m pytest tests/test_admin.py -k history tests/test_membership.py -q
```

`python -P frontend/tests/admin_history_ui.py` 在仓库根目录运行，使用 :8000 已构建前端，全部 API 模拟。

人工验收：管理员打开 `/admin/history`，与不同账号的前台历史对照标题、状态和用户邮箱；检查搜索、翻页、查看文稿及手机布局。实际列表为空时表示现有表没有符合保留/隐藏规则的记录，不会虚构示例数据。
