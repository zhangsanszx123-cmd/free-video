# FreeVideo 万能视频下载

基于开源项目 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 的在线视频下载站：粘贴链接即可下载 B站、YouTube、TikTok、X、微博等 1800+ 站点的视频 / MP3 / 字幕，支持批量打包 ZIP、AI 视频总结与双语字幕翻译（DeepSeek）。电脑、手机浏览器均可使用。

> 仅供个人学习研究。请尊重版权，勿下载、传播未经授权的内容；频繁下载可能触发平台风控。

文档：[需求分析](docs/requirements.md) ｜ [方案设计](docs/design.md)

## 技术栈
- 后端：Python 3.12 + FastAPI，直接调用 yt-dlp Python API（不修改其源码），无数据库，内存任务队列 + 临时文件自动清理
- 前端：Vue 3 + Vite + Tailwind CSS v4 + vue-router
- 依赖：本机需安装 **ffmpeg**（合并音视频、转 MP3、转换字幕）

## 快速开始

```bash
# 1. 后端
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # 按需填写 DEEPSEEK_API_KEY / YTDLP_PROXY

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

## API
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/parse` `{url}` | 解析元信息、清晰度、字幕、可用直链（支持分享口令中提取链接） |
| POST | `/api/download` `{url, quality, kind}` | 创建下载任务（`kind`: video/audio） |
| POST | `/api/batch` `{urls[], quality, kind}` | 批量下载并打包 ZIP |
| POST | `/api/subtitles` `{url, lang}` | 下载 SRT 字幕 |
| POST | `/api/ai/summary` `{url}` | AI 总结（SSE 流式） |
| POST | `/api/ai/translate` `{url, target_lang}` | 生成双语 SRT 任务 |
| GET | `/api/jobs/{id}` / `/api/jobs/{id}/file` | 任务进度 / 下载文件 |

## 测试
```bash
cd backend
.venv\Scripts\python -m pytest              # 单元测试（mock yt-dlp / openai）
.venv\Scripts\python -m pytest -m network   # 真实网络冒烟测试（B站）
```

## 已知限制
- 不使用 Cookie：需登录的内容（如抖音、部分小红书、B站大会员画质）无法下载
- AI 功能依赖视频字幕，无字幕视频暂不支持（后续可接入 faster-whisper 语音识别）
- 定价页仅为展示，未接入真实支付
