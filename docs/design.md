# FreeVideo 方案设计文档

> 版本：v1.2（新增字幕优先的云端转写）｜ 需求见 [requirements.md](./requirements.md)
> 扩展功能前请先阅读本文档的「设计原则」与「扩展指南」。

> 视频转文字方案已批准并实现；后续用户明确只提供百炼 Key，已批准切换默认到 paraformer-realtime-v2。详见[开发方案](./video-to-text-plan.md)、[配置与验收](./video-to-text-setup.md)，新增架构见本文第 8 节；真实云端识别效果待填写 Key 后联调。

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

元信息 `extract_info(download=False)` 显式设置 `writesubtitles/writeautomaticsub`，避免 B 站提取器跳过 `_get_subtitles`。薄包装的诊断 logger 识别锁定版本的登录字幕警告，标记内部 `subtitle_login_required`；解析结果的 `subtitle_notice` 将具体原因传给前端，字幕列表为空时优先显示该原因，不被通用提示覆盖。字幕提取接口返回相同原因。网络错误仍作为错误，不改第三方源码、不读取账号 Cookie。样本 BV1mAAmzqEfP 的 view 接口登记中文轨道，匿名 player 接口返回 `need_login_subtitle=true` 与空列表，不能把它描述为“视频没有字幕”。
B 站匿名字幕兜底（`bilibili_subs.py`）：yt-dlp 报告登录字幕警告后，`extract_info` 调用 `bilibili_subs.tracks(info)`：`x/web-interface/view`（按分 P 取 cid/aid）→ `x/v2/dm/view` 取带 `auth_key` 的字幕地址，仅保留 `hdslb.com` 域名、非空地址、非机器翻译（`ai_type=0`）的轨道，结果存入 `info["bilibili_subtitles"]`；`list_subtitles` 合并这些轨道，`download_subtitle` 命中时直接下载 JSON 转 SRT，不经 yt-dlp。请求不带 Cookie；任何失败返回空并保持原有“需要登录”提示。该接口未公开，失效时跑 `pytest -m network -k login_subtitle`。

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
| POST | `/api/transcript` | `{url, lang?}` | `{text, timed_text, cues}` / 400 `{detail}` |
| POST | `/api/ai/summary` | `{url}` | SSE：`status` / `meta{title,thumbnail,cues}` / `delta` / `done` / `error`；未启用 503 |
| POST | `/api/ai/translate` | `{url, target_lang}` | Job；未启用 503 |
| GET | `/api/jobs/{id}` | – | Job / 404 |
| GET | `/api/jobs/{id}/file` | – | 文件（RFC5987 中文文件名）/ 404 |
| GET | `/{path}` | – | dist 静态文件或 `index.html`（SPA fallback，防目录穿越） |

`/api/parse` 响应：`{url, id, title, description, tags[], thumbnail, images[], duration, uploader, platform, view_count, qualities[{height,label,size,pro}], has_audio, audio_url, subtitles[{lang,name,auto}], direct{url,height,ext}|null}`

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
- `ResultCard.vue`：对齐 AnyToCopy 提取结果布局，分为顶栏（导出 TXT/MD、加入选题、AI 创作）及五大卡片区块：标题与简介（原“文案内容”，标题、正文描述、`#话题` 标签复制、生成爆款）、视频内容（内嵌播放器、清晰度选择、下载视频、复制链接）、音频内容（在线 `<audio>` 播放与 MP3 提取下载）、视频文案（异步获取字幕文稿、纯文本/时间戳切换、复制与下载 SRT）、图片内容（封面/图集网格预览与下载）。
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
| 扩展语音识别服务商 | 在 `asr.py` 实现 Provider 并注册；保持独立转写队列、预算和鉴权，不在 `tasks.fetch_transcript` 隐式触发收费 |
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

## 8. 视频转文字扩展（v1.2）

2026-11-08 当前默认：`asr_flash.py`，注册名 `fun-asr-flash`，模型 `fun-asr-flash-2026-06-15`。经 HTTPS/Base64 发送 MP3/WAV，只需百炼 Key；SSE 按起始时间替换累计快照，校验全文与真实词时间戳。使用 `direct-http` 账本类型，请求前持久化；明确拒绝释放额度，断线或不完整结果保留预占且不重发，重启不把请求标识当作可查询文件任务。

用户确认速度优先。超过 5 分钟先准备全部连续 280 秒 WAV 分段，默认每视频并发两段（可配置 1–4），按原顺序及采样偏移合并。预算按各段向上取整秒数总和预占，按每段最大 usage 向上取整后结算。部分失败保留已完成段费用，禁止整条重试；任何未决段保留整条预占。默认任务并发 2，最多同时 4 个云请求。MP3/PCM/分段 WAV 终态清理。无采样缺口或重叠，边界准确性待人工验收。下述实时方案为此前实现，仍可显式选择，但不再是默认；最新配置见配置指南。

### 8.1 模块与调用链

```text
ResultCard → TranscriptPanel
  ├─ /api/transcript：同步、只提取平台字幕，返回来源/语言/text/timed_text/cues/srt
  └─ 用户点击 → /api/transcription-session（建立签名匿名会话）
              → POST /api/transcriptions {url, lang?, allow_asr:true}
              → TranscriptionManager（独立线程池、锁、队列上限、去重）
                  ├─ 复核可下载字幕，有字幕即结束，ASR 次数 0
                  └─ downloader 音轨 → ffprobe → ffmpeg 单声道 16k/64kbps MP3
                      ├─ 默认：PCM → 预算预占 → 加密 WebSocket 直接发送音轨
                      │   → recognize → 最终句子 + task-finished → Recognition/Cue
                      └─ 可选文件适配：预算预占 → 私有 OSS 签名 URL → submit/query
                      → TXT/SRT + 文字预览 → 清理本地音轨（文件适配另清理 OSS 输入）
```

- `asr.py` 定义 `Provider`、`Recognition` 和注册表；`asr_realtime.py` 使用锁定的 websockets 直接实现官方协议，不引入 DashScope SDK。实时适配器通过 `recognize(pcm,on_submit,cancel)` 返回最终结果，`on_submit` 在启动消息发送前记账。默认只检查百炼 Key 和实时配置，不检查 OSS。
- 实时发送与接收并发；收到 task-started 后以约 100ms 的 PCM 帧发送，等待 task-finished 才认为完整成功。只保存 sentence_end 的最终句子，词级时间戳可补齐服务端空 end_time；累计 usage 取最大值，不逐句相加。
- 原 `paraformer-v2` 文件适配器仍用已有 httpx 的 submit/query，仅该可选路径要求 OSS。
- `storage.py` 薄封装官方 oss2，支持 V4 签名及可选 STS，输入对象前缀为 `freevideo-asr/`，不设公开 ACL。
- `asr_ledger.py` 进程内锁＋fsync＋原子替换维护用量账本；按实际音频时长预占，优先用云返回 usage 结算，未决预占跨日保留。存储任务 ID 和待清理对象标识，不存正文/签名 URL。
- `transcription_auth.py` HMAC 签名的匿名 Cookie，HttpOnly、SameSite=Strict，可配置 Secure、稳定密钥、来源白名单；创建按会话/直连 IP 限速。
- `transcriptions.py` 处理有类型的无字幕/空字幕、下载音轨、实际时长大小校验、云任务、导出与恢复。不同分享 URL 解析成同一规范 URL 后指向同一拥有者的任务，防止重复收费。
- `NoSubtitles`/`EmptySubtitles` 与网络/鉴权错误分开；后者禁止隐式识别回退。抖音先验证作品可访问，再报告本项目未提取到字幕。

### 8.2 API 与存储

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/transcription-session` | 签发/校验匿名会话，返回 `{ok}`，无敏感内容 |
| POST | `/api/transcriptions` | `{url,lang?,allow_asr:false}`；明确允许时才在无可用字幕后识别 |
| GET | `/api/transcriptions/{id}` | 所有者查询 `{id,status,stage,message,error,error_code,retryable,title,result,...}` |
| GET | `/api/transcriptions/{id}/file?format=txt\|srt` | 所有者导出；文件不接入旧通用下载路由 |

`result={text,timed_text,cues,source,language,srt}`；来源 `platform_subtitle|automatic_subtitle|asr`。未报告识别语言时返回 null，不猜测，也不把字幕选择当成翻译指令。异步错误码区分配置、容量、音轨超限、预算、无人声、云端状态不明等；不暴露云任务 ID、签名 URL 或服务商原始错误。

`ASR_DIR/results/<id>/` 保存结果，与 `DOWNLOAD_DIR` 分开，避免旧清理线程误删。任务活动期间不按结果 TTL 删除；从任务结束起计 30 分钟。私有目录还有 `usage.json` 与开发环境生成的 `session.key`，不能通过静态文件服务提供。HTTP 客户端普通日志禁用，避免记录签名结果地址。

### 8.3 恢复与边界

默认实时路径在本地解码 PCM，压缩源仍受 100MB 限制，解码后最长一小时约 115.2MB，处理结束后清理 MP3/PCM。预算默认按北京实时单价 0.00024 元/秒预占，最终按累计云端用量结算，缺失用量则按预占结算。WebSocket 客户端 UUID 不能通过文件任务接口查询；启动后断线或进程重启只标为 unknown 并保留预占，不重发音轨，本期不提供流式断点恢复。启动前失败可释放预占。

可选旧文件适配器仍每 60 秒核对未决云任务和待删除对象：有云任务 ID 的只查询，不重新提交；不明提交保留预占供人工核对。签名 URL 到期后加 1 小时回收未知对象，OSS 生命周期兜底。重启不恢复任务正文；配置环境变化时不误操作旧对象。两种传输在账本中用 transport 区分，不会把实时 UUID 当成可查询的文件任务 ID。

仅限单进程，不支持多个 worker 共享账本。新增会话隔离不涵盖原有下载路由；匿名会话也不替代账号计费系统。本期 AI 总结/翻译继续仅用已有平台字幕，不隐式消费 ASR。更多配置、部署和验收见 [video-to-text-setup.md](./video-to-text-setup.md)。

## 9. AI 视频精读与助学扩展架构（v1.3）

遵循开闭原则，v1.3 助学能力以独立模块挂载，原有 `/api/ai/*`、`ai.py`、`AiTools.vue` 保持零修改：
- **后端模块**：`learning_text.py`（紧凑时间轴合并、分段与关键词检索） → `ai_learning.py`（默认 `AI_LEARNING_MODEL=deepseek-flash`，`AI_LEARNING_THINKING=disabled`，支持单次 6 万字直通与 6～18 万字 Map-Reduce 分段汇总、Markdown 导图树生成、多轮追问） → `ai_learning_api.py`（`APIRouter(prefix="/api/learn")`，使用 FastAPI 内置 `EventSourceResponse` + `ServerSentEvent`，提供 `POST /api/learn/summary`、`/mindmap`、`/chat` 及同 IP 速率限制）。
- **文稿解析与安全边界**：按「请求直传 `transcript` → 当前签名会话拥有的已完成 `Transcription` → `read_subtitles` 免费平台字幕」顺序解析；无字幕时返回 `need_asr` 事件或 `409 NEED_ASR`，绝不在后端隐式发起收费云端 ASR，且严格校验 `transcription_auth` 会话归属防跨用户读取。
- **前端模块**（`frontend/src/learning/`）：独立 `Marked` + `DOMPurify` + `DOMParser` 安全时间戳胶囊转换（`markdown.js`）、自研 Vue 3 + SVG 交互脑图（`MindMapView.vue`，支持全屏沉浸浏览、2x PNG / SVG / MD 导出）、三合一助学面板（`AiLearningPanel.vue`）、首页输入框一体式框内左对齐高对比双选项卡与结果卡片双视图分流（`Home.vue` + `ResultCard.vue`，含 B站/YouTube 嵌入播放器回退及双视图文稿同步）及左右分栏工作台（`pages/LearnWorkbench.vue`，路由 `/learn`）。详见 [ai-learning-plan.md](./ai-learning-plan.md)。
