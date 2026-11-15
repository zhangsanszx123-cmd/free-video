# FreeVideo 万能视频下载

基于开源项目 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 与 [f2](https://github.com/Johnserf-Seed/f2)（抖音）的在线视频下载站：粘贴链接即可下载抖音、B站、YouTube、TikTok、X、微博等 1800+ 站点的视频 / MP3 / 字幕，支持批量打包 ZIP、AI 视频总结与双语字幕翻译（DeepSeek）。电脑、手机浏览器均可使用。

> 仅供个人学习研究。请尊重版权，勿下载、传播未经授权的内容；频繁下载可能触发平台风控。

文档：[需求分析](docs/requirements.md) ｜ [方案设计](docs/design.md) ｜ [视频转文字配置与验收](docs/video-to-text-setup.md) ｜ [账号功能验收](docs/account-verification.md) ｜ [会员额度与本机管理](docs/membership-quota-plan.md) ｜ [会员与历史任务验收](docs/membership-verification.md) ｜ [ZPAY 支付配置与验收](docs/zpay-setup.md)

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

开发模式：后端 `uvicorn app.main:app --reload --port 8000`，前端 `npm run dev`（Vite 自动把 `/api` 代理到 8000，访问 http://127.0.0.1:5173；测试支付时把 `PUBLIC_BASE_URL` 改为该地址）。

- 修改 `.env` 后需重启后端才生效；`Ctrl+C` 停止服务。
- 启动报 `[Errno 10048] ... 8000`：端口已被另一个后端占用。先关闭那个终端，或执行 `Get-NetTCPConnection -LocalPort 8000 -State Listen | % { Stop-Process -Id $_.OwningProcess }` 后重试。

## 配置（backend/.env）
| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek Key，留空则 AI 功能显示"未启用" |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | 默认 `https://api.deepseek.com` / `deepseek-chat`，任何 OpenAI 兼容服务均可 |
| `YTDLP_PROXY` | 访问海外平台的代理，如 `http://127.0.0.1:7890` |
| `MAX_WORKERS` | 并发任务数，默认 3 |
| `FILE_TTL_MINUTES` | 临时文件保留时间，默认 30 |
| `MAX_FILESIZE_MB` | 单文件上限，默认 1024 |
| `MAX_BATCH` | 批量条数的全局硬上限，默认 20；各套餐单次上限（免费 3 / 月卡 10 / 年卡 15）在数据库套餐表中配置 |
| `ASR_MAX_DURATION` | 单条语音识别的全局硬上限（秒），默认 3600；各套餐上限（免费 8 / 月卡 30 / 年卡 60 分钟）在套餐表中配置 |
| `DASHSCOPE_API_KEY` | 音频转文字唯一云端凭证；默认 fun-asr-flash-2026-06-15，无需 OSS |
| `ASR_DAILY_BUDGET` | 全站每日识别估算额度，默认 10 元，账本持久化 |
| `FFMPEG_BINARY` / `FFPROBE_BINARY` | 可选完整路径，默认从 PATH 查找 |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | 账号数据库，默认 `127.0.0.1:3306`、`root`、`freevideo`；数据库不可用时账号接口返回 503，游客解析/下载也会受影响（游客名额记录在数据库中） |
| `MYSQL_TEST_DATABASE` | pytest 专用库（会清空表，必须与 `MYSQL_DATABASE` 不同），留空则跳过账号测试 |
| `AUTH_SESSION_DAYS` | 登录有效期，默认 7 天 |
| `AUTH_REGISTER_RATE_LIMIT` / `AUTH_LOGIN_RATE_LIMIT` | 每 IP 注册（10 分钟）/ 登录（1 分钟）次数上限，默认 5 / 10 |
| `ZPAY_PID` / `ZPAY_KEY` | ZPAY 商户 ID 与密钥（密钥只放 .env）；都为空且未开模拟时定价页显示“在线支付暂未开放” |
| `ZPAY_MOCK` | `true` 使用本机模拟收银台（不扣钱，生产 `SESSION_SECURE=true` 时自动禁用） |
| `PUBLIC_BASE_URL` | 本站对外地址，拼接支付回调与返回页，须与浏览器访问地址一致，默认 `http://127.0.0.1:8000` |
| `ZPAY_GATEWAY` / `PAYMENT_ORDER_TTL_MINUTES` / `PAYMENT_RECONCILE_SECONDS` | 网关（默认 `https://zpayz.cn`）、未支付订单复用时长（30 分钟）、后台对账间隔（60 秒，0 关闭） |

## API
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/parse` `{url}` | 解析元信息、清晰度、字幕、可用直链（支持分享口令中提取链接）；游客最多解析 2 个不同链接，用完返回 403 `GUEST_LIMIT` |
| POST | `/api/download` `{url, quality, kind}` | 创建下载任务（`kind`: video/audio）；游客只能下载已解析的链接 |
| POST | `/api/batch` `{urls[], quality, kind}` | 批量下载并打包 ZIP（需登录） |
| POST | `/api/subtitles` `{url, lang}` | 下载 SRT 字幕（需登录） |
| POST | `/api/transcript` `{url, lang?}` | 仅提取已有字幕，输出文字、时间戳、SRT 和来源（需登录） |
| POST | `/api/transcriptions` `{url, lang?, allow_asr}` | 异步字幕优先；显式允许后才调用云端识别（需登录） |
| GET | `/api/transcriptions/{id}` / `/api/transcriptions/{id}/file?format=txt\|srt` | 会话保护的转写状态／导出 |
| POST | `/api/ai/summary` `{url}` | AI 总结（SSE 流式，需登录） |
| POST | `/api/ai/translate` `{url, target_lang}` | 生成双语 SRT 任务（需登录） |
| POST | `/api/batch-transcriptions`、`/api/learn/*` | 批量字幕、AI 学习工作台（需登录） |
| POST | `/api/auth/register` / `login` / `logout`，GET `/api/auth/me` | 注册、登录、退出、当前用户 |
| PATCH/POST/GET/DELETE | `/api/account/profile` / `password` / `sessions` / `/api/account` | 个人中心：昵称、改密、登录设备、注销 |
| GET | `/api/plans`、`/api/account/membership`、`/api/account/history*` | 套餐、会员额度、历史任务 |
| POST/GET | `/api/pay/orders` `{plan}`、`/api/pay/orders/{no}` | 创建支付宝订单（需登录）、我的订单、查询并确认支付结果 |
| GET/POST | `/api/pay/notify` | ZPAY 异步通知（验签 + 查单确认，返回纯文本 success） |
| GET | `/api/jobs/{id}` / `/api/jobs/{id}/file` | 任务进度 / 下载文件 |

## 测试
```bash
cd backend
.venv\Scripts\python -m pytest              # 单元测试（mock yt-dlp / f2 / openai）
.venv\Scripts\python -m pytest -m network   # 真实网络冒烟测试（B站 + 抖音）
```
账号测试连接 `MYSQL_TEST_DATABASE`（真实 MySQL）；浏览器端到端流程见 [账号功能验收](docs/account-verification.md)。支付测试 `tests/test_payments.py` 不访问真实 ZPAY，浏览器支付流程见 `frontend/tests/payment_ui.py` 文件头。

## 已知限制
- 不使用账号 Cookie：需登录的内容（如部分小红书、B站大会员画质）无法下载
- 抖音：仅支持视频（图文作品暂不支持），当前适配器不提取字幕轨道；可配置云端音频转文字，首期不联动无字幕 AI 总结。平台风控更新可能导致暂时失效，需升级 f2
- YouTube：部分视频会触发人机验证（出口 IP 被风控），可更换代理节点后重试
- 视频转文字优先读取已有字幕，无字幕时调用 fun-asr-flash-2026-06-15；只需百炼 Key，无需 OSS。超过 5 分钟自动分段并发识别、合并时间轴，整条最长 60 分钟
- AI 总结/翻译本期仍依赖平台字幕；没有自动联动收费识别
- 多人转写仅支持单进程，状态目录需持久化；生产需 HTTPS 和会话配置。实时连接中断不自动重发音轨，未决费用保留供核对，详见配置指南
- 游客只能免费解析并下载 2 个不同视频（Cookie + IP 双重记录，永不重置），这 2 个视频的时长在该浏览器首次登录/注册时补扣当月识别额度；字幕提取、识别、批量、AI 都需登录。登录用户下载不限次数。
- 套餐使用上限（数值存数据库，可用 `python -m app.membership configure` 调整）：AI 视频总结每周期 10 / 300 / 500 个视频（同一视频的总结、导图、追问共算 1 个，失败不扣），AI 追问每天 1 / 10 / 20 条，批量单次 3 / 10 / 15 条，单条识别最长 8 / 30 / 60 分钟（免费 / 月卡 / 年卡）
- 语音识别需登录，每个账号使用当前套餐的一套额度：免费每月 30 分钟、月卡 19.9 元/每月 10 小时、年卡 99 元/每月 30 小时，Pro 不叠加免费额度。免费按注册时间、Pro 按开通时间逐月重置（北京时间，短月取月底）；登录后下载与平台字幕提取免费，历史文稿保存 30 天
- 在线支付通过 ZPAY 仅支持支付宝页面跳转收银台；同档续费顺延、月卡可升级年卡，年卡期间不可购买月卡。本机无公网 IP 时靠主动查单与后台对账入账，配置与测试见 [ZPAY 支付配置与验收](docs/zpay-setup.md)；套餐价格仍由本机命令配置，见 [会员额度方案](docs/membership-quota-plan.md)
- 支付对账线程为单进程实现，多实例部署只在一个实例开启
