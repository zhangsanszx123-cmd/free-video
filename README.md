# FreeVideo 万能视频下载

基于开源项目 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 与 [f2](https://github.com/Johnserf-Seed/f2)（抖音）的在线视频下载站：粘贴链接即可下载抖音、B站、YouTube、TikTok、X、微博等 1800+ 站点的视频 / MP3 / 字幕，支持批量打包 ZIP、AI 视频总结与双语字幕翻译（DeepSeek）。电脑、手机浏览器均可使用。

> 仅供个人学习研究。请尊重版权，勿下载、传播未经授权的内容；频繁下载可能触发平台风控。

文档：[需求分析](docs/requirements.md) ｜ [方案设计](docs/design.md) ｜ [视频转文字配置与验收](docs/video-to-text-setup.md) ｜ [账号功能验收](docs/account-verification.md) ｜ [会员额度与本机管理](docs/membership-quota-plan.md) ｜ [会员与历史任务验收](docs/membership-verification.md)

## 技术栈
- 后端：Python 3.12 + FastAPI，直接调用 yt-dlp Python API；抖音链接走 f2（开发分支，固定 commit，使用自动生成的匿名访客 Cookie，不登录）。均不修改源码；内存任务队列 + 临时文件自动清理；**MySQL 8.x**（PyMySQL）保存站内账号、登录会话、会员额度和 30 天转录任务历史
- 前端：Vue 3 + Vite + Tailwind CSS v4 + vue-router
- 依赖：本机需安装 **ffmpeg**（合并音视频、转 MP3、转换字幕）与 **MySQL 8.x**（账号功能）

## 快速开始

```bash
# 1. 后端
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # 填写 MYSQL_PASSWORD，按需填写 DEEPSEEK_API_KEY / YTDLP_PROXY
mysql -u root -p < sql/schema.sql  # 创建 freevideo 与 freevideo_test 库（启动时也会自动建表）

# 2. 前端构建（生产模式由 FastAPI 直接托管 dist）
cd ../frontend
npm install
npm run build

# 3. 启动（单端口，手机在同一局域网访问 http://<电脑IP>:8000）
cd ../backend
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

开发模式：后端 `uvicorn app.main:app --reload --port 8000`，前端 `npm run dev`（Vite 自动把 `/api` 代理到 8000）。

## 配置（backend/.env）
| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek Key，留空则 AI 功能显示"未启用" |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | 默认 `https://api.deepseek.com` / `deepseek-chat`，任何 OpenAI 兼容服务均可 |
| `YTDLP_PROXY` | 访问海外平台的代理，如 `http://127.0.0.1:7890` |
| `MAX_WORKERS` | 并发任务数，默认 3 |
| `FILE_TTL_MINUTES` | 临时文件保留时间，默认 30 |
| `MAX_FILESIZE_MB` | 单文件上限，默认 1024 |
| `MAX_BATCH` | 批量下载上限，默认 20 |
| `DASHSCOPE_API_KEY` | 音频转文字唯一云端凭证；默认 fun-asr-flash-2026-06-15，无需 OSS |
| `ASR_DAILY_BUDGET` | 全站每日识别估算额度，默认 10 元，账本持久化 |
| `FFMPEG_BINARY` / `FFPROBE_BINARY` | 可选完整路径，默认从 PATH 查找 |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | 账号数据库，默认 `127.0.0.1:3306`、`root`、`freevideo`；数据库不可用时游客功能照常，账号接口返回 503 |
| `MYSQL_TEST_DATABASE` | pytest 专用库（会清空表，必须与 `MYSQL_DATABASE` 不同），留空则跳过账号测试 |
| `AUTH_SESSION_DAYS` | 登录有效期，默认 7 天 |
| `AUTH_REGISTER_RATE_LIMIT` / `AUTH_LOGIN_RATE_LIMIT` | 每 IP 注册（10 分钟）/ 登录（1 分钟）次数上限，默认 5 / 10 |

## API
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/parse` `{url}` | 解析元信息、清晰度、字幕、可用直链（支持分享口令中提取链接） |
| POST | `/api/download` `{url, quality, kind}` | 创建下载任务（`kind`: video/audio） |
| POST | `/api/batch` `{urls[], quality, kind}` | 批量下载并打包 ZIP（需登录） |
| POST | `/api/subtitles` `{url, lang}` | 下载 SRT 字幕 |
| POST | `/api/transcript` `{url, lang?}` | 仅提取已有字幕，输出文字、时间戳、SRT 和来源 |
| POST | `/api/transcriptions` `{url, lang?, allow_asr}` | 异步字幕优先；显式允许后才调用云端识别 |
| GET | `/api/transcriptions/{id}` / `/api/transcriptions/{id}/file?format=txt\|srt` | 会话保护的转写状态／导出 |
| POST | `/api/ai/summary` `{url}` | AI 总结（SSE 流式，需登录） |
| POST | `/api/ai/translate` `{url, target_lang}` | 生成双语 SRT 任务（需登录） |
| POST | `/api/batch-transcriptions`、`/api/learn/*` | 批量字幕、AI 学习工作台（需登录） |
| POST | `/api/auth/register` / `login` / `logout`，GET `/api/auth/me` | 注册、登录、退出、当前用户 |
| PATCH/POST/GET/DELETE | `/api/account/profile` / `password` / `sessions` / `/api/account` | 个人中心：昵称、改密、登录设备、注销 |
| GET | `/api/jobs/{id}` / `/api/jobs/{id}/file` | 任务进度 / 下载文件 |

## 测试
```bash
cd backend
.venv\Scripts\python -m pytest              # 单元测试（mock yt-dlp / f2 / openai）
.venv\Scripts\python -m pytest -m network   # 真实网络冒烟测试（B站 + 抖音）
```
账号测试连接 `MYSQL_TEST_DATABASE`（真实 MySQL）；浏览器端到端流程见 [账号功能验收](docs/account-verification.md)。

## 已知限制
- 不使用账号 Cookie：需登录的内容（如部分小红书、B站大会员画质）无法下载
- 抖音：仅支持视频（图文作品暂不支持），当前适配器不提取字幕轨道；可配置云端音频转文字，首期不联动无字幕 AI 总结。平台风控更新可能导致暂时失效，需升级 f2
- YouTube：部分视频会触发人机验证（出口 IP 被风控），可更换代理节点后重试
- 视频转文字优先读取已有字幕，无字幕时调用 fun-asr-flash-2026-06-15；只需百炼 Key，无需 OSS。超过 5 分钟自动分段并发识别、合并时间轴，整条最长 60 分钟
- AI 总结/翻译本期仍依赖平台字幕；没有自动联动收费识别
- 多人转写仅支持单进程，状态目录需持久化；生产需 HTTPS 和会话配置。实时连接中断不自动重发音轨，未决费用保留供核对，详见配置指南
- 语音识别需登录，免费用户每月 30 分钟；月卡 19.9 元/10 小时每月，年卡 99 元/30 小时每月；北京时间每月 1 日重置。下载与平台字幕提取免费，历史文稿保存 30 天
- 未接入真实支付，暂由服务器本机命令开通会员与配置套餐；操作与验收见 [会员额度方案](docs/membership-quota-plan.md)
