# 游客免费 AI 视频总结体验验证与验收

日期：2026-11-28。已完成本地实现、生产构建与自动化验证，待用户人工验收。

## 最终行为与规则

- 游客在首页切换至「AI 视频总结」选项卡并点击「AI 总结」（或回车提交）时，累计可免费体验 1 个视频的 AI 总结，视频（及字幕/实际音轨）时长上限为 3 分钟（180 秒），无平台字幕时自动包含免费语音转写。
- 按签名 Cookie + 出口 IP 双重永久记录（`guest_ai_subjects`），任一已使用、进行中或状态待核对（`uncertain`）均拦截新体验；清 Cookie 无法重置。体验结果仅原 Cookie 所属浏览器可读（`guest_ai_trials` 保留 30 天，到期清理文稿但不重置终身占用）。
- 与游客 2 个视频下载名额独立互不消耗；游客首次登录或注册时，AI 总结体验的时长**不补扣**账号每月语音识别额度。
- 未产生任何总结输出时释放名额并允许重试，重试同一视频复用已识别文稿，不重复调用收费 ASR；若已输出部分总结或云端识别状态不明（`SUBMISSION_UNCERTAIN`）则保留占用且禁止自动重发音轨。
- 体验名额已用完、视频超过 3 分钟、时长无法确认或文稿超限时，弹出登录窗并展示对应提示，登录成功后在原页继续执行账号 AI 总结；页面被动恢复已有体验结果时不弹窗打断浏览。

## 修改位置

- 后端：`backend/app/guest_ai_trial.py`、`backend/app/guest_ai_api.py`（`/api/guest/ai-summary`）、`backend/app/guest.py`（`trial_identity`）、`backend/app/transcriptions.py`（`max_duration`）、`backend/app/main.py`、`backend/sql/schema.sql`（`guest_ai_trials`、`guest_ai_subjects`）。
- 前端：`frontend/src/components/GuestAiTrialPanel.vue`、`frontend/src/pages/Home.vue`、`frontend/src/api.js`、`frontend/src/data.js`、`frontend/src/pages/Pricing.vue`、`frontend/src/components/MobileCtaBar.vue`、`frontend/src/components/UpgradeModal.vue`。
- 测试：`backend/tests/test_guest_ai_trial.py`、`frontend/tests/guest_ai_trial_ui.py`、`frontend/tests/ui_regression.py`、`frontend/tests/account_ui.py`、`backend/tests/conftest.py`。

## 自动化验证

| 检查 | 结果 |
|---|---|
| 后端专项（`test_open_api.py` / `test_open_api_urls.py` / `test_guest_ai_trial.py` / `test_transcriptions.py`） | 87 passed（独立 `freevideo_open_api_test` 数据库，含真实 MySQL 事务锁、模拟平台/ASR/大模型） |
| 游客 AI 体验浏览器测试（`guest_ai_trial_ui.py`） | 10 passed（含 `:8000` 生产构建 1440px/390px 截图、轮询防重提、超限/超长登录衔接、被动恢复、XSS 过滤、状态不明仅查原任务、输入改动丢弃迟到响应） |
| 开放 API 浏览器与示例脚本测试（`open_api_ui.py` / `open_api_examples.py`） | 全部通过（1440px/390px、Python 与 Node.js 示例同键重试与恢复） |
| 原有界面回归（`ui_regression.py` / `frontend_followup_ui.py`） | 27 + 4 项全部通过 |
| 前端生产构建 | `npm run build` 成功 |
| 差异格式 | `git diff --check` 通过 |

复跑命令（PowerShell，仓库根目录）：

```powershell
$env:MYSQL_TEST_DATABASE='freevideo_open_api_test'
cd backend
.venv/Scripts/python -m pytest tests/test_guest_ai_trial.py -q
```

前端（`:8000` 或 Vite `:5178`）：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:UI_BASE_URL='http://127.0.0.1:8000'
python -P frontend/tests/guest_ai_trial_ui.py
```

截图位于本机忽略目录 `.runtime/guest-ai-ui/`。

## 人工验收

1. 在未登录（或无痕窗口）下打开 `http://127.0.0.1:8000/`，点击「AI 视频总结」选项卡，确认直接切换模式且不弹登录窗，下方提示「游客可免费总结 1 个视频，最长 3 分钟，含无字幕转写」。
2. 粘贴一个 3 分钟以内的视频链接，点击「AI 总结」，确认在首页展示体验进度与总结结果卡片（含复制总结、时间戳跳转及「登录使用脑图与追问」入口）；刷新页面可自动恢复已生成的体验结果。
3. 再次粘贴第二个不同视频链接并点击「AI 总结」（或粘贴超过 3 分钟的视频），确认自动弹出登录窗并提示体验名额已用完（或超过 3 分钟上限），登录成功后在原页继续执行账号 AI 总结。
