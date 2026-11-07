# FreeVideo 方案设计文档

> 版本：v1.1（与当前代码一致，新增抖音适配）｜ 需求见 [requirements.md](./requirements.md)
> 扩展功能前请先阅读本文档的「设计原则」与「扩展指南」。

## 1. 设计原则
1. **封装而非魔改**：解析/下载能力来自开源项目的 Python API（通用平台用 yt-dlp，抖音用 f2），只做薄封装；不 fork、不改源码，升级只需改版本号。新平台适配器统一挂在 `downloader.py` 的入口上按域名分流，`tasks.py` / `main.py` / 前端无需改动。
2. **轻量**：无数据库，内存任务表 + 本地临时目录；单进程单端口部署。
3. **任务化**：耗时操作（下载、批量、字幕、翻译）统一走 `JobManager` 异步任务 + 前端轮询；只有 AI 总结用 SSE 流式。
4. **错误对用户友好**：底层异常统一转换为 `VideoError`（中文提示），由接口层返回 400 或写入任务 `error`。
5. **前端设计系统集中**：视觉 token 在 `style.css`，文案/数据在 `data.js`，页面只做组合。

## 2. 总体架构
```
浏览器 (Vue3 SPA)
  │  /api/*  (JSON / SSE)            生产：FastAPI 同端口托管 frontend/dist
  ▼
FastAPI (app/main.py) ── 路由、参数校验、SSE、文件下发、SPA fallback
  ├─ downloader.py  ── 统一入口 + yt-dlp 薄封装：extract_url / parse / download / download_subtitle / friendly_error
  │    └─ douyin.py ── 抖音域名分流到 f2：fetch_detail / summarize / download（访客 Cookie + httpx 流式下载）
  ├─ errors.py      ── VideoError（用户可见的中文错误）
  ├─ jobs.py        ── Job 数据类 + JobManager(ThreadPoolExecutor) + 过期清理线程
  ├─ tasks.py       ── 任务体：single_download / batch_download / subtitle_download / translate_subtitle
  ├─ ai.py          ── DeepSeek(OpenAI SDK)：summarize_stream / translate_cues
  ├─ subtitles.py   ── SRT 解析、去重、转纯文本、生成双语 SRT
  └─ config.py      ── 读取 backend/.env
        │
        ▼
yt-dlp / f2  +  ffmpeg（合并音视频 / 转 MP3 / 字幕转换）      backend/downloads/<job_id>/  (TTL 30 分钟)
```

## 3. 目录结构
```
free-video/
  backend/
    app/  main.py config.py errors.py downloader.py douyin.py jobs.py tasks.py ai.py subtitles.py
    tests/  conftest.py test_downloader.py test_douyin.py test_api.py test_network.py(-m network)
    requirements.txt  .env.example  pytest.ini
  frontend/
    src/
      main.js router.js App.vue api.js store.js data.js style.css
      components/ NavBar SiteFooter MobileCtaBar UpgradeModal Icon JobProgress ResultCard FaqList
      pages/ Home Batch AiTools Pricing
    vite.config.js（dev 代理 /api → :8000）  index.html  public/logo.svg
  docs/ requirements.md design.md
  README.md AGENTS.md
```

## 4. 后端设计
### 4.1 yt-dlp 封装要点（downloader.py）
| 能力 | 实现 |
|---|---|
| 通用参数 | `base_opts()`：quiet、`noplaylist`、超时/重试、`windowsfilenames`、可选 `proxy`(YTDLP_PROXY) |
| 链接提取 | `URL_RE` 从分享口令中取第一个 http(s) 链接（遇中文标点截断） |
| 解析 | `extract_info(url, download=False)`；playlist 取第一个有效 entry；`summarize()` 输出前端所需字段 |
| 清晰度 | 按 `height` 去重降序；大小取 `filesize`/`filesize_approx`，否则 `tbr*125*duration` 估算；≥1080 标记 `pro` |
| 直链判定 `_pick_direct` | http(s) 协议 + mp4 + 同时含音视频 + 无 cookies + 无 Referer/Cookie 头；YouTube 排除（链接绑定服务器 IP） |
| 视频下载 | `format = bv*[height<=H]+ba/b[height<=H]/bv*+ba/b`，`format_sort=[res, vcodec:h264, ext:mp4:m4a]`（优先手机兼容的 h264），`merge_output_format=mp4` |
| 音频 | `format=ba/b` + `FFmpegExtractAudio(mp3, 192)` |
| 字幕 | `writesubtitles + writeautomaticsub + subtitleslangs=[lang] + skip_download` + `FFmpegSubtitlesConvertor(srt)` |
| 进度 | 先 `extract_info(download=False)` 得到 `requested_formats` 数量（阶段数），再 `process_ie_result(info, download=True)`；`progress_hooks` 计算总体进度，`postprocessor_hooks` 上报"合并/转码中" |
| 产物定位 | 每个任务独立目录，下载后按文件大小取最大文件（排除 .part/.ytdl） |
| 错误映射 | `friendly_error()` 关键字规则表 → 中文提示；新增平台错误时在此追加规则 |

字幕语言优先级 `SUB_PREFERENCE`：zh-Hans > zh-CN > zh > zh-Hant > zh-TW > ai-zh > en > en-US > en-orig > ja > ko；平台字幕优先于自动字幕；忽略 danmaku/live_chat。

### 4.1.1 抖音适配（douyin.py，基于 f2）
**为什么不用 yt-dlp**：yt-dlp 的 `DouyinIE` 请求详情接口时需要浏览器验证脚本生成的签名 Cookie（`s_v_web_id`），源码中为 TODO，直接报 `Fresh cookies (not necessarily logged in) are needed`。

**依赖**：`f2` GitHub 开发分支 `v0.0.1.8-pw3`，固定 commit `f6be8c0`（requirements.txt 用 codeload zip 安装，GitHub git 协议在本机网络不可用）。PyPI 版 0.0.1.7（2024-12）签名过时，实测 403。

| 能力 | 实现 |
|---|---|
| 分流 | `downloader.parse / download / download_subtitle` 入口先 `douyin.is_douyin(url)`（`douyin.com`、`iesdouyin.com` 及子域，含 `v.douyin.com` 短链） |
| 作品 ID | 先用正则匹配 `/video/<id>`、`/note/<id>`、`modal_id=<id>`；否则调 f2 `AwemeIdFetcher.get_aweme_id`（跟随短链重定向） |
| 访客 Cookie | `TokenManager.gen_ttwid()` + `gen_real_msToken()` 拼成 Cookie，进程内缓存 20 分钟（加锁）；**不涉及任何账号** |
| 详情 | `DouyinHandler(kwargs).fetch_one_video(aweme_id)._to_dict()`，f2 负责 a_bogus 签名；f2 是 async，在线程池里用 `asyncio.run` 调用 |
| 重试 | 失败时刷新访客 Cookie 重试 1 次；"已删除/私密/链接无法识别"等确定性错误不重试 |
| 输出 | `summarize()` 转为与 yt-dlp 相同的结构：`qualities=[]`（前端显示"原画·最佳画质"）、`subtitles=[]`、`direct=play_addr[0]`（直链无需 Referer） |
| 下载 | 每次下载前重新取详情（播放地址会过期），`httpx.stream` 逐块写入并上报进度/速度/ETA，多个播放地址依次回退；超 `MAX_FILESIZE_MB` 拒绝 |
| MP3 | 下载 MP4 后 `ffmpeg -vn -c:a libmp3lame -b:a 192k` 转码，删除中间 MP4 |
| 不支持 | 图文作品（`images` 非空）→ `VideoError("暂不支持抖音图文作品")`；字幕/AI → `VideoError("抖音作品没有字幕…")` |
| 日志 | 调用时把 `f2` logger 调到 WARNING，避免 rich 输出刷屏 |

风险：抖音风控与签名算法会变化，失效时优先升级 f2 commit（同样遵守"发布满 7 天"规则），再跑 `pytest -m network`。

### 4.2 任务模型（jobs.py）
`Job` 字段：`id, kind, status(queued|running|processing|done|error), progress, speed, eta, title, thumbnail, message, error, filename, items[], created_at, filepath(不序列化)`；`to_dict()` 额外输出 `ready`。

- `JobManager.submit(kind, fn)`：`fn(job) -> Path`，在线程池执行；返回值即下载文件。任务体通过 `job.update(**fields)` 上报进度。
- 异常：`VideoError/AIDisabled` → 原文作为 `error`；其他异常记录日志并返回通用提示。
- 清理：守护线程每 60s 删除超过 TTL 且已结束的任务及目录，并清理重启后遗留的孤儿目录。
- 限制：进程内存储，重启丢失任务；多进程/多实例部署需改为 Redis 等共享存储（见扩展指南）。

### 4.3 任务体（tasks.py）
- `batch_download`：`dedupe_urls` 去重 → 逐条下载到 `job.dir/01、02…` → 子项状态写入 `job.items` → 成功文件以 `序号_文件名` 存入 ZIP（`ZIP_STORED`，视频不再压缩）；全部失败则报错。
- `translate_subtitle`：`fetch_transcript` 下载并解析字幕 → `ai.translate_cues` 分块翻译 → 生成 `标题.双语.<语言>.srt`。

### 4.4 AI（ai.py）
- OpenAI SDK + `DEEPSEEK_BASE_URL`，任何 OpenAI 兼容服务可直接替换（改 `.env`）。
- 总结：字幕带 `[mm:ss]` 时间戳转纯文本，超过 15000 字截断；`stream=True` 逐段 yield。
- 翻译：每块 40 条，输入 `序号|原文`，要求输出 `序号|译文` 并按序号回填，缺失行保留为空（只显示原文），保证时间轴不错位。

### 4.5 API
| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/health` | – | `{ok, ai_enabled, max_batch}` |
| POST | `/api/parse` | `{url}` | 视频信息（见下）/ 400 `{detail}` |
| POST | `/api/download` | `{url, quality?, kind: video\|audio}` | Job |
| POST | `/api/batch` | `{urls[], quality?, kind}` | Job（`items[]` 为子任务） |
| POST | `/api/subtitles` | `{url, lang?}` | Job |
| POST | `/api/ai/summary` | `{url}` | SSE：`status` / `meta{title,thumbnail,cues}` / `delta` / `done` / `error`；未启用 503 |
| POST | `/api/ai/translate` | `{url, target_lang}` | Job；未启用 503 |
| GET | `/api/jobs/{id}` | – | Job / 404 |
| GET | `/api/jobs/{id}/file` | – | 文件（RFC5987 中文文件名）/ 404 |
| GET | `/{path}` | – | dist 静态文件或 `index.html`（SPA fallback，防目录穿越） |

`/api/parse` 响应：`{url, id, title, thumbnail, duration, uploader, platform, view_count, qualities[{height,label,size,pro}], has_audio, subtitles[{lang,name,auto}], direct{url,height,ext}|null}`

### 4.6 配置（backend/.env）
`DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, YTDLP_PROXY, MAX_WORKERS=3, FILE_TTL_MINUTES=30, MAX_FILESIZE_MB=1024, MAX_BATCH=20, DOWNLOAD_DIR`

## 5. 前端设计
### 5.1 页面与路由
| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | Home | Hero + 输入框（MP4/MP3/SRT 模式）+ ResultCard + 统计 + 功能 + 三步 + 平台表 + 场景 + FAQ + CTA；支持 `?url=&mode=` 自动解析 |
| `/batch` | Batch | 多链接文本框、实时识别条数、类型/清晰度、子任务列表 + ZIP |
| `/ai` | AiTools | 总结（SSE + marked + DOMPurify）/ 翻译（任务）；`?url=` 预填；health 检测未启用 |
| `/pricing` | Pricing | 三档方案、倒计时、对比表、FAQ |

### 5.2 关键模块
- `api.js`：`request`（统一抛出 `detail`）、`pollJob`（轮询至 done/error，返回取消函数）、`streamSSE`（POST + ReadableStream 解析 SSE）、`triggerDownload`、`fmt`（大小/时长/计数）、`extractUrls`。
- `JobProgress.vue`：通用任务进度条 + 保存按钮，`slot` 可插入子任务列表。所有新任务型功能复用它。
- `ResultCard.vue`：解析结果、清晰度/字幕选择、发起任务、直链秒下（`window.open`，跨域 download 属性无效）、跳转 AI。
- `store.js`：全局 `ui.openUpgrade(reason)` 弹出升级弹窗。

### 5.3 视觉设计系统（style.css，参考 anytocopy.com）
| Token | 用途 |
|---|---|
| `.hero-bg` | `#f8fbff` + 44px 网格线 + 蓝/翠绿/靛紫三层渐变光晕 |
| `.text-grad` / `.btn-primary` | 主渐变 `#2563eb → #6366f1 → #8b5cf6`；按钮 hover 上浮 1px |
| `.text-gold` / `.btn-gold` / `.pro-badge` | 金橙色系，用于付费/PRO 元素（与主色区分，形成转化焦点） |
| `.glass-card` / `.input-shell` / `.input-control` | 毛玻璃卡片、1.75rem 圆角输入外壳、聚焦靛蓝光环 |
| `.progress-stripes` | 进行中条纹动画 |
| `.prose-ai` | AI Markdown 排版 |

付费引导手法：PRO 角标、"限时 5 折"提示条、年卡深色高亮 + "最受欢迎"、划线价、折合每日价、当日倒计时、权益对比、移动端底部升级条、CTA 区。

## 6. 测试策略
- `tests/test_downloader.py`：`FakeYDL` 替身模拟 yt-dlp（含 hooks 与产物写入），覆盖链接提取、清晰度/直链/字幕选择、进度计算、MP3/字幕参数、错误映射、SRT 工具。
- `tests/test_api.py`：TestClient + monkeypatch 覆盖全部接口、任务成功/失败、批量部分失败与 ZIP、AI 未启用/SSE/翻译、过期清理。
- `tests/test_douyin.py`：域名识别、summarize、错误映射、刷新 Cookie 重试/确定性错误不重试、播放地址回退与进度、downloader 分流（全部 mock，不联网）。
- `tests/test_network.py`（`-m network`）：真实 B站解析、360P、MP3；真实抖音解析、MP4（校验 ftyp）、MP3。
- UI：Edge headless 截图（桌面 1280/1440；手机用 390px iframe 规避窗口最小宽度）。

## 7. 扩展指南（给后续 AI 的约定）
| 想做的事 | 改哪里 |
|---|---|
| 新的下载类任务 | `tasks.py` 新增 `xxx(...) -> run(job) -> Path` → `main.py` 加路由 `manager.submit(kind, fn)` → 前端 `api.js` 加方法 + 复用 `pollJob` / `JobProgress` |
| 新的 AI 能力 | `ai.py` 加函数（复用 `_client()`，未启用抛 `AIDisabled`）；流式用 `_sse` 模式，非流式走任务 |
| 无字幕 ASR（B1） | 在 `tasks.fetch_transcript` 中字幕缺失时：下载音频 → whisper 转写为 `Cue` 列表，其余流程不变 |
| 账号/历史/付费（B2/B3） | 引入 SQLite + 鉴权中间件；额度校验放在创建任务的路由层；前端 `ui.openUpgrade` 已是统一入口 |
| Cookie（B4） | `base_opts()` 按域名注入 `cookiefile`；同步修改 FAQ/页脚合规文案 |
| 播放列表（B5） | 去掉 `noplaylist` 并复用 `batch_download` 逻辑处理 entries |
| 新平台报错文案 | `downloader.friendly_error` 规则表 + 对应单测（抖音在 `douyin.friendly_error`） |
| 新平台适配器（yt-dlp 不支持时，如小红书/快手 B10） | 参照 `douyin.py`：提供 `is_xxx / parse / download`，返回与 `summarize()` 相同结构；在 `downloader.parse / download / download_subtitle` 入口加分流；补 mock 单测 + network 测试 |
| 抖音图集（B9） | `douyin.summarize` 中 `images` 分支返回图片列表 → 新增下载为 ZIP；前端 ResultCard 增加图集展示 |
| 新页面 | `pages/` + `router.js`（含 `titles`）+ `NavBar.links` |
| 多实例部署 | 任务表换 Redis、文件放共享存储/对象存储；线程池可换 Celery/RQ |

约定：
- 保持 yt-dlp / f2 零修改；升级先跑 `pytest -m network`。
- 新增依赖锁版本，且版本发布已满 7 天。
- 用户可见文案用中文，错误通过 `VideoError` 抛出。
- 改动后验证：`pytest`、`npm run build`，必要时截图检查移动端。
