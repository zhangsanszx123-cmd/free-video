# FreeVideo 方案设计文档

## 2026-11-11 定价页样式

`Pricing.vue` 恢复原版 `glass-card`、年卡深色金边及 `btn-gold` 等视觉样式和权益对比布局，保留 `/api/plans` 数据来源以及现有会员开通说明。未改动额度结算和数据库配置。

时长以独立圆角高亮区块展示，标题与大号额度数字分层；普通套餐延续靛紫色，年卡延续金色，数据仍通过 `durationLabel(plan.monthly_seconds)` 渲染。

## 2026-11-11 会员额度与历史任务架构

- `membership.py`：MySQL 套餐种子、配置修订号、会员权益快照、自然月额度、预占/结算/释放流水、30 天文稿历史和重启核对。金额为整数分，用户用量按实际音频整秒向上取整；供应商计费口径不影响用户扣量。
- 六张增量表定义于 `backend/sql/schema.sql`：`membership_plans`、`user_memberships`、`user_quota_periods`、`transcription_records`、`quota_reservations`、`quota_events`。启动自动建表并仅首次写入默认套餐，不覆盖已有配置。
- `main.py` 单条 ASR 使用 `current_user`，无登录账号拒绝识别；批量接口使用 `require_user`。任务 owner 为服务端生成的 `user:<id>`，状态/导出/AI 学习复用均校验账号归属；游客的平台字幕与下载继续免费。登录用户调用 `/api/transcript` 时也记录免费字幕历史。
- `transcriptions.py` 在云端提交前事务预占用户秒数，再预占既有全站成本预算；任一步失败补偿释放。结果发布和用户结算在同一事务提交；普通失败释放，未知提交保留。任务跨月仍结算原预占周期，跨期未决预占暂占新周期可用量。
- 每个账号的额度变更先锁用户行，保证并发不超额；事件以 `(job_id,action)` 唯一实现幂等。会员到期恢复免费额度且保留本月已用/预占；人工开通替换本月额度，不叠加、不清零使用量。暂不支持有效会员提前续费或跨档升级。
- 内存任务仍是单进程队列，数据库保存可跨设备读取的任务、文本与状态。重启不自动重新发送音轨；未提交任务释放额度，未知提交保留核对。成功结果可从数据库复用和导出；临时媒体沿用原 30 分钟 TTL。
- `membership_api.py`：只读公开 `GET /api/plans`；登录接口 `GET /api/account/membership`、`GET /api/account/history?page=&search=&status=`、`GET /api/account/history/{id}`、`GET .../{id}/file?format=txt|srt`、`DELETE /api/account/history/{id}`。状态筛选 `all/active/done/error`；20 条/页。移出历史仅隐藏展示，不修改用量；到期后台物理清理记录和文本，额度流水保留核对。
- 前端 `membership.js` 共享额度状态并在身份变化时清空；`QuotaCard.vue` 用于个人中心及账号菜单，`History.vue` 负责执行中/历史记录，`Pricing.vue` 从服务端读取配置。保留首字母头像；移除旧折扣与无限免费识别宣传。本期无在线支付或管理后台页面。
- 运维命令、配置生效范围与测试见 [会员额度方案](./membership-quota-plan.md) 和 [验收记录](./membership-verification.md)。

## 2026-11-11 提取结果模式入口简化

- `ResultCard.vue` 移除结果标题旁的两个重复模式按钮，保留标题与导出等操作。
- `Home.vue` 上方模式选项卡继续控制 `activeView`，结果视图及登录拦截沿用现有逻辑。结果卡头部在 xl 以下纵向排列。

## 2026-11-11 个人中心交互优化

- `Account.vue` 用 `active` 控制四个分区，默认基本资料；桌面侧栏、手机横向滚动导航，以 `aria-current` 标识当前分区。资料保存、改密或注销期间禁止切换分区。
- 个人中心及 `NavBar.vue` 复用原有 `UserAvatar.vue` 展示首字母头像；头像仅展示，不提供上传或编辑入口。保留原有账号和路由鉴权规则、后端 API 与 MySQL 表结构。
- 昵称取消操作恢复最新服务端资料；监听账号昵称更新，仅在本地无修改时同步输入框。`account.js` 收到同身份的跨标签页事件也刷新资料，刷新不广播，避免循环。
- 密码分别维护当前密码、新密码、确认密码错误；设备刷新使用加载锁，与下线操作互斥，结果当前设备置顶。
- 注销区域独立展示，确认表单按需挂载；取消或离开分区清空敏感输入。原密码与用户名验证仍由服务端执行。
- 测试沿用独立 MySQL 测试库，覆盖分区切换、取消、字段校验、跨标签页同步和响应式布局。

## 0. 2026-11-10 用户账号架构（v1.5）

**模块**（后端独立挂载，原有任务模型不变）：
- `account_store.py`：PyMySQL 原生 SQL，每次调用一个短连接（connect_timeout 5s）+ 事务；`init_schema()` 执行 `backend/sql/schema.sql` 中的 `CREATE TABLE IF NOT EXISTS`（单一建表来源）。唯一索引冲突 1062 → 409「该用户名已被注册」，其它 MySQL 错误 → `AccountError` 503「账号服务暂不可用」。lifespan 启动时建表，失败只记日志。
- `account_auth.py`：`hashlib.scrypt`（n=2^14、r=8、p=1、16 字节盐，格式 `scrypt$n$r$p$salt$hash`，`compare_digest`；未知用户名比对假哈希以统一耗时）；会话令牌 `token_urlsafe(32)`，库中只存 sha256；Cookie `freevideo_auth`（HttpOnly、SameSite=Lax、Path=/api、Secure 跟随 `SESSION_SECURE`、7 天）；`current_user` 最多每 5 分钟刷新 last_seen；`require_user` 依赖返回 401 `AUTH_REQUIRED`；来源校验规则同 `transcription_auth.check_origin`；进程内限速（注册每 IP 10 分钟 5 次、登录每 IP 每分钟 10 次、单用户名 15 分钟失败 5 次、改密/注销每用户 10 分钟 5 次，前两项可配置）。
- `account_api.py`：`APIRouter`，全部响应 `Cache-Control: no-store`，写接口校验来源。`errors.AccountError` 由 `main.py` 统一转 `{detail, code}`。
- 拦截：`main.py` 给 `/api/batch`、`/api/batch-transcriptions*`、`/api/ai/summary`、`/api/ai/translate` 加 `Depends(require_user)`；`ai_learning_api.router` 在 `include_router(..., dependencies=[Depends(require_user)])` 处整体拦截。`/api/jobs/*`、单条下载/转写保持开放。批量字幕/转写的数据所有者仍是匿名签名会话。

**表**（utf8mb4/InnoDB，时间为 UTC `DATETIME(6)`）：`users(id, username, username_key UNIQUE, nickname, password_hash, created_at, updated_at, password_changed_at)`；`sessions(id 对外设备 ID, token_hash UNIQUE, user_id FK ON DELETE CASCADE, created_at, last_seen_at, expires_at, user_agent, ip)`。注册在一个事务内创建用户与首个会话；改密在一个事务内更新哈希并删除全部会话；登录时清理过期会话。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/register` | `{username,password,nickname?}`，注册并登录 |
| POST | `/api/auth/login` | `{username,password}`；失败统一 401「用户名或密码错误」 |
| POST | `/api/auth/logout` | 删除当前会话并清 Cookie，可重复调用 |
| GET | `/api/auth/me` | `{user}`，游客 `{user:null}`（失效 Cookie 顺带清除）；数据库故障 503 |
| PATCH | `/api/account/profile` | `{nickname}` |
| POST | `/api/account/password` | `{old_password,new_password}`，撤销全部会话 |
| GET | `/api/account/sessions` | `{sessions:[{id,device,ip,created_at,last_seen_at,expires_at,current}]}` |
| DELETE | `/api/account/sessions/{id}` | 只能下线自己的设备，否则 404 |
| POST | `/api/account/sessions/revoke-others` | `{revoked}` |
| DELETE | `/api/account` | `{password,confirm_username}`，删除用户与会话 |

用户对外字段只有 `id, username, nickname, created_at`。状态码：401 未登录/凭据错误、403 跨站、404、409 重名、422 校验、429 限速、503 数据库不可用。

**前端**：
- `src/account.js`：`accountApi`、校验规则 `rules`（与后端一致，按码点计长）、`safeRedirect`（仅 `/` 开头且非 `//`、`/\`，排除登录/注册页）、reactive `account`（`status: unknown|guest|authed|error`、`ensure/refresh/login/register/logout/markLoggedOut(reason)`，reason 为 `logout|password_changed|deleted|expired`）、弹窗状态 `authModal` + `openAuth({tab, notice, redirect, onSuccess})` / `closeAuth()`。已登录身份结束或切换时（非首次解析、非游客登录）递增 `version`；BroadcastChannel `fv-auth`（storage 事件兜底）通知其它标签页重新拉取 `me`；`fv-auth-last-user` 记录上次身份，变化时清除 `fv-batch-subtitles`。`api.js`、`learnApi.js` 遇到 `AUTH_REQUIRED` 调用 `markLoggedOut()`。
- `router.js`：`meta.requiresAuth`（`/batch`、`/ai`、`/learn`、`/account`）与 `meta.guestOnly`（备用页 `/login`、`/register`），`beforeEach` 等待 `account.ensure()`；游客访问受保护路由时 `openAuth({redirect: to.fullPath})`，站内导航返回 `false` 留在当前页，首次加载改去首页。守卫只负责交互，后端始终校验。
- `App.vue`：挂载 `AuthModal` 与全局提示（`ui.notify`）；`RouterView` 以 `路由名:version` 为 key，已登录身份结束或切换时重建页面丢弃旧结果/轮询（游客登录不重建，便于原地继续操作）。监听 `account.user.id`：登出时受保护页面回首页；`password_changed`/`expired` 打开登录弹窗并显示原因（expired 带回原页面），`deleted` 仅提示；已登录停留在备用登录页则回跳。
- 页面/组件：`components/AuthModal.vue`（原生 `<dialog>.showModal()`，登录/注册 Tab、焦点循环、Esc/遮罩关闭；成功后执行 `onSuccess` 或跳转 `redirect`，监听 `account.loggedIn` 保证其它标签页登录时也只完成一次）、`LoginForm.vue` / `RegisterForm.vue`（弹窗与备用页共用）、备用页 `pages/Login.vue`、`Register.vue`（`AuthShell.vue` 布局）、`Account.vue`、`FormField.vue`（标签、错误、显示密码、autofocus）、`UserAvatar.vue`（字母渐变头像）；`NavBar` 游客「登录/注册」按钮打开弹窗，登录后桌面头像下拉（个人中心/退出）、手机菜单账号卡片与退出；`Home.vue` 游客点 AI Tab 弹登录窗，成功后原地继续；`MobileCtaBar` 在账号页及首次导航完成前隐藏。

**测试**：`tests/test_accounts.py` 连接真实 `MYSQL_TEST_DATABASE`（未配置则跳过；与主库同名时拒绝运行）；`conftest.py` 用 `dependency_overrides` 让其余用例以已登录身份运行，并禁止测试触碰主库。`frontend/tests/account_ui.py` 对真实后端 + 测试库跑浏览器全流程；`ui_regression.py`、`batch_subtitles_ui.py` 额外 mock `/api/auth/me` 为已登录。详见 [账号功能验收](./account-verification.md)。

**限制**：限速在进程内，多进程需共享存储；每请求新建连接，高并发时可换连接池；任务未归属账号，下载历史（B2）需统一所有者模型。

## 2026-11-10 批量字幕架构（v1.4）

- `NavBar.vue` 的共享 `links` 在 `/learn` 后增加 `/batch` 批量提取入口，桌面与手机共用导航顺序及当前页面高亮。

- 验收修订：`Batch.vue` 默认 `kind=subtitle`，格式列表字幕在首位。`api.js` 的 `downloadArchive` 共用于视频/音频 ZIP 和字幕 ZIP：仅 fetch JSON 任务状态，确认终态与 `ready`/`succeeded` 后，附加唯一 `_download` 参数，使用原生链接将文件传输交给浏览器或下载管理器。不再 fetch ZIP 正文、Range 预检或前端签名校验，避免 IDM 接管后产生误判，也避免大包缓存到内存。下载锚点延后移除；任务状态查询错误显示在页面，传输后的错误由浏览器/IDM 展示。

- `batch_transcriptions.py` 的 `BatchTranscriptionManager` 是独立的轻量编排器，两个线程顺序提交每批链接至现有 `TranscriptionManager`。不另写云端识别实现、不绕过预算预占与去重、不自动重试收费提交；单条失败继续下一条。全局最多 10 个未结束批次。
- `POST /api/batch-transcriptions` 接收 `urls`、显式 `allow_asr: true`；使用签名匿名会话、来源检查及创建限速。相同会话、相同有序去重链接在结果有效期内复用同一批次（含失败结果），不会隐式重新识别。
- `GET /api/batch-transcriptions/{id}` 返回每条阶段、错误、字幕来源、正文、带时间戳正文及 SRT。`GET .../{id}/file` 仅在批次终态且有成功结果时生成 ZIP，全部接口检查归属并禁止缓存；ZIP 编号前缀防重名，清洗路径字符，只包含成功的 SRT。
- 每条完成后复制结果到批次内存，避免早完成的单条转写先过期导致整批无法导出。批次按完成时间判断 TTL；查询/提交时清理过期批次。单进程内存状态不跨重启恢复，费用账本的未决处理沿用既有规则。
- `transcriptions.py` 对现有「字幕需登录」的 `NoSubtitles` 异常显式阻止付费回退；真正无轨道/空轨道仍走已授权的 ASR。
- `BatchSubtitleResults.vue` 管理字幕批次提交、轮询和恢复（localStorage 仅保存 ID），网络轮询失败仅重查同一任务。字幕使用文本插值呈现，不使用 `v-html`；ZIP 查询 JSON 状态后原生下载，单条 SRT 使用已返回结果本地导出。
- `Batch.vue` 保留视频/音频流程；输入区 896px 居中，结果区最大 1152px，桌面左右分栏、手机纵向；费用提示放在提交按钮上方。根任务完成后才开放 ZIP，已完成字幕在其余任务运行时可预览、复制或单条下载。
- 测试覆盖见 [批量字幕验收记录](./batch-subtitles-verification.md)。

## 2026-11-10 UI 交互实现补充

- `style.css` 的 `batch-banner` 管理首页批量入口视觉；CSS 伪元素绘制点阵和圆弧，装饰不接收指针事件，整个横幅仍为单一 RouterLink。桌面左右排列，手机按钮独占一行。

- 首页模式选项卡容器仅负责 flex 排列与间距；按钮自身负责视觉状态，不再叠加外层底框。

- `frontend/src/useParseRequest.js` 集中管理解析请求：`AbortController` 取消 + 版本号校验，防止不响应取消的旧请求发布结果；卸载时取消。首页与学习工作台同步监听输入变化，清空操作同时清理关联状态。
- `ResultCard` 视频/音频各自维护提交锁；结果变更与卸载递增请求版本，忽略迟到提交。`Batch`、`AiTools` 的提交锁纳入 `busy`，卸载标记阻止迟到响应启动轮询。
- 首页独立健康检查控制器，5 秒超时、30 秒重查，卸载清理定时器与请求；API `health`、`parse` 支持可选 `AbortSignal`。
- `UpgradeModal` 使用原生 `<dialog>.showModal()` 隔离背景交互，并补充 Tab 首尾循环；浏览器负责关闭后恢复焦点，组件同步全局开关和 body 滚动状态。
- `MobileCtaBar` 同步根元素 `mobile-cta-visible` 类；`style.css` 仅在移动端按悬浮条显示状态预留 body 底部与滚动安全区。页脚取消固定的大块升级条留白；导航按钮补充展开状态语义。
- 新增浏览器回归脚本 `frontend/tests/ui_regression.py`，使用现有 Python Playwright 环境，模拟全部 API，不添加运行时依赖、不调用收费服务。操作方法见 [验证记录](./ui-polish-verification.md)。

> 版本：v1.2（新增字幕优先的云端转写）｜ 需求见 [requirements.md](./requirements.md)
> 扩展功能前请先阅读本文档的「设计原则」与「扩展指南」。

> 视频转文字方案已批准并实现；后续用户明确只提供百炼 Key，已批准切换默认到 paraformer-realtime-v2。详见[开发方案](./video-to-text-plan.md)、[配置与验收](./video-to-text-setup.md)，新增架构见本文第 8 节；真实云端识别效果待填写 Key 后联调。

## 1. 设计原则
1. **封装而非魔改**：解析/下载能力来自开源项目的 Python API（通用平台用 yt-dlp，抖音用 f2），只做薄封装；不 fork、不改源码，升级只需改版本号。新平台适配器统一挂在 `downloader.py` 的入口上按域名分流，`tasks.py` / `main.py` / 前端无需改动。
2. **轻量**：内存任务表 + 本地临时目录；单进程单端口部署。仅账号与登录会话使用 MySQL（v1.5，见第 0 节）。
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
`DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, YTDLP_PROXY, MAX_WORKERS=3, FILE_TTL_MINUTES=30, MAX_FILESIZE_MB=1024, MAX_BATCH=20, DOWNLOAD_DIR`；账号：`MYSQL_HOST/PORT/USER/PASSWORD/DATABASE, MYSQL_TEST_DATABASE, AUTH_SESSION_DAYS=7, AUTH_REGISTER_RATE_LIMIT=5, AUTH_LOGIN_RATE_LIMIT=10`

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
| 需登录的新接口 | 路由加 `dependencies=[Depends(account_auth.require_user)]`（或读取 `user=Depends(...)`）；前端路由加 `meta.requiresAuth` |
| 下载历史/付费（B2/B3） | 账号已在 MySQL；新增任务/额度表放 `account_store.py`，额度校验放在创建任务的路由层；前端 `ui.openUpgrade` 已是统一入口 |
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
