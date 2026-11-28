# FreeVideo 方案设计文档

## 2026-11-28 游客 2 个视频名额开放字幕与文案提取

- `/api/subtitles`、`/api/transcript`、`/api/transcriptions`（POST）对未登录游客不再直接返回 401 `AUTH_REQUIRED`，而是调用 `guest.require_known(request, url)` 校验请求链接属于当前游客（Cookie 或 IP）已成功解析的 2 个视频名额（`guest_links`）内；未解析或超出 2 个名额返回 403 `GUEST_LIMIT`。
- 游客调用 `/api/transcriptions` 使用 `transcription_auth.owner(request, response)` 签名会话隔离任务归属，并设置 `max_duration = min(480, ASR_MAX_DURATION)`（单条上限 8 分钟）。
- `TranscriptPanel.vue` 移除 `guestPrompt` 强制登录块，游客解析名额内视频后自动请求 `/api/transcript` 或在无平台字幕时发起 `/api/transcriptions`；若返回 `GUEST_LIMIT` / `AUTH_REQUIRED` 则调用 `openAuth` 弹窗并在登录成功后原地续作。

## 2026-11-28 游客免费 AI 视频总结体验

- `guest_ai_trial.py/guest_ai_api.py` 提供 `/api/guest/ai-summary`（`GET` 状态与最近任务、`POST` 异步提交、`GET /{trial_id}` 轮询），强制同源校验、`no-store` 及按 Cookie owner + IP 的创建（10/分钟）与读取限流。
- `guest.trial_identity` 复用 `freevideo_guest` 签名 Cookie（无 Cookie 时签发），返回 `owner = sha256(cookie_subject)` 及排序后的 `[owner, sha256(ip_subject)]`；不写入 `guest_links`，不触发登录时长认领。
- 表 `guest_ai_trials` 保存 `owner,raw_key,video_key,state,payload,transcription_id,expires_at`（结果仅匹配 `owner` 可读，保留 30 天）；表 `guest_ai_subjects` 保存 `subject,trial_id,state(available|reserved|used|uncertain)`，故意不建外键，结果过期清理后仍永久保留体验占用。
- `_reserve` 按排序后的 `subject` 行锁串行化并发请求：同 `owner` 已有未失败（或已有部分总结）的同视频任务直接幂等复用；若任一 `subject != available` 抛 403 `GUEST_AI_LIMIT`；首次失败且无总结输出的重试复用上次已保存的 `info/transcript`，避免二次收费识别。
- `TrialManager._run` 先解析并校验元数据时长 `<= 180s`（未知抛 `GUEST_AI_DURATION_UNKNOWN`，超长抛 `GUEST_AI_TOO_LONG`）；无缓存文稿时调用 `TranscriptionManager.submit('trial:'+owner, canonical, allow_asr=True, max_duration=180, on_accept=_bind)`，音轨下载后再次校验实际时长，通过 `on_accept` 在发送云请求前持久化 `transcription_id`。
- 字幕/转写完成后先校验 SRT 末句时间轴 `<= 180s` 与压缩文稿长度 `<= 20000` 并落盘 `transcript`，再流式调用 `ai_learning.summarize_events`；首个非空 summary 增量落盘时即把 `guest_ai_subjects` 置为 `used`。空输出失败回退为 `available`；ASR 状态不明（`SUBMISSION_UNCERTAIN` 或账本 `submitting/submitted/unknown`）置为 `uncertain` 并冻结名额，重启 `recover()` 仅核对账本与本地已结算 SRT，绝不自动重发 ASR 或大模型请求。
- 前端 `Home.vue` 在游客提交 AI 总结前先请求 `GET /api/guest/ai-summary` 落盘签名 Cookie 并检查状态，再 `POST` 创建或复用任务、每 2 秒轮询；挂载时被动恢复已有体验任务（若用户已编辑输入或切换动作则丢弃迟到响应）。遇到 `GUEST_AI_LIMIT / GUEST_AI_TOO_LONG / GUEST_AI_DURATION_UNKNOWN / GUEST_AI_TEXT_TOO_LONG` 时调用 `openAuth` 弹窗并在登录成功后原地续作账号总结。`GuestAiTrialPanel.vue` 复用安全 Markdown 渲染与平台时间戳外跳，隐藏脑图与追问并引导登录。验证见 [记录](./guest-ai-trial-verification.md)。

## 2026-11-28 首页 AI 模式预览与提交鉴权

- `Home.selectTab(view)` 对 `download` 与 `ai` 两个选项卡均仅同步更新 `activeView` 与 `actionVersion` 并停止旧游客轮询，不调用 `parse`、不自动提交、不递增总结触发序号；所有解析、提取和身份/额度检查均保留在 `submitWithView` 显式按钮/表单提交路径。
- submitWithView 捕获动作版本，解析完成后只有版本、视图和输入仍匹配才触发总结，避免 AI 提交期间切换下载再切回 AI 恢复旧意图；每次新 parse 前清零 autoSummarizeSeq，避免 ResultCard 内 AI 面板重新挂载时沿用旧正值发起隐藏总结。
- 既有共享链接 guest fallback、登录后原地续作和服务端鉴权保持原有规则。相关浏览器验证见 [记录](./home-ai-login-verification.md)。

## 2026-11-28 视频文案提取开放 API

- `open_api_auth.py/open_api_store.py/open_api_api.py` 新增独立 Bearer 鉴权、MySQL 密钥摘要与 API 请求授权、版本化路由和独立 OpenAPI Schema；共享现有 TranscriptionManager、账号时长事务与供应商账本，不改变网页 Cookie 路由或套餐价格。详见 [方案](./open-api-plan.md) 与 [接入文档](./open-api.md)。
- `open_api_keys` 持久化凭证摘要、密码快照摘要、名称、前缀、创建/使用/撤销时间；认证锁用户后复核密钥及账号状态，管理端创建复核网站会话。改密、找回重置、后台禁用在既有事务中撤销密钥；注销级联删除。
- `open_api_requests` 使用账号级唯一幂等键、请求摘要、稳定外部 task_id、内部转写 ID、过期时间；账号行锁完成准入后释放 SQL 锁，再进入进程提交锁/管理器锁。TranscriptionManager.submit 新增内部可选 job_id/on_accept，在入队或返回复用任务之前写入授权映射；API 恢复仅核对映射，不重新提交。活动计数解析别名实际目标，避免别名 done 隐藏仍在运行的任务。
- 开放状态映射为 queued/running/succeeded/failed/uncertain；未知提交优先映射 uncertain。OpenRoute 统一参数/业务/意外错误与 request_id、no-store、Retry-After；公开 schema 仅列四条开放业务路由和相关模型、Bearer 和幂等头，不混入后台接口。
- Transcription.media 记录 source_url/video_url/cover_url/platform/duration_seconds，通过 membership.persist 与历史 JSON 一起保存、恢复；原始 yt-dlp 信息先转现有 summarize 结构，抖音沿用 direct.url。字幕与 ASR 分支均保存，别名查询可从 SQL 恢复目标。平台直链可为空且不承诺 30 天有效；查询不重新解析或重发 ASR。
- 首版只开放固定平台的视频 ID 路径，分享短链逐跳验证域名/公网 DNS，规范化后交给原适配器；不能仅靠入口校验承诺第三方适配器全部出站行为安全。单进程与生产网络边界沿用现有部署要求。
- 前端 ApiKeys.vue/ApiDocs.vue 复用现有设计与账号隔离；秘密只在组件内存中展示，离页清除，不存 localStorage。NavBar.links 在「批量提取」后、「定价」前显示公开的「API」，桌面与手机菜单共用配置，指向 /account/api/docs；页脚保留文档入口，个人中心及账号菜单提供管理入口。手机不显示遮挡操作的升级浮层。验证及验收见 [记录](./open-api-verification.md)。
- 顶部导航链接禁止收缩和换行；768–1023px 的账号按钮保留头像与下拉箭头、收起昵称，避免新增入口与长昵称挤占导航。昵称仍在账号下拉内完整可见，1024px 起恢复按钮昵称展示。

## 2026-11-17 后台现有历史汇总

- `GET /api/admin/history {page,search,status}` 复用后台 require_admin 与 no-store，调用 `membership.history(None, ...)`；仅内部后台代码可传 None 汇总，前台接口仍从 require_user 取得实际用户 ID，不能由请求指定任意拥有者。
- `membership.history` 复用原表及 quota_reservations 关联，保留过滤、搜索和分页；后台额外关联现有 users.email 返回 user_email，用于列表/详情展示邮箱；原 user_id 仅作内部归属，不展示。前台响应不增加邮箱字段，仍移除 user_id/fingerprint。排序补 id 降序以稳定同时间分页，不改 schema 或历史写入。
- `AdminHistory.vue` 复用 AdminPagination/AdminDialog/useAdminList；useAdminList 允许传状态白名单，默认用户/管理员列表选项不变。详情只渲染 Vue 文本，原视频链接仅允许 http/https，无删除、导出或后台重新提交任务操作。

## 2026-11-17 套餐额度独立管理

- `GET /api/admin/plan-limits` 返回三档套餐及批量/单条识别实际系统上限；`PATCH /api/admin/plan-limits/{free|monthly|yearly}` 接收 revision、monthly_minutes、ai_monthly_limit、chat_daily_limit、batch_max_links、asr_max_minutes，全部严格正整数，拒绝额外字段。
- monthly_minutes 上限 525600，AI/追问上限 1000000；另两项以当前 MAX_BATCH 和 ASR_MAX_DURATION/60 为上限。分钟转整数秒持久化。写操作复用 guard/actor/session→plan 行锁，复核权限和版本，五项原子更新并 revision+1，与 plan.limits_update 审计同事务；不变值不增版本。与价格共用套餐 revision，避免跨页面覆盖。
- `membership._entitlement` 付费时长改取当前套餐；`_quota` 在个人用户锁下同步本期 limit_seconds，保留已用/预占/周期；历史周期不批量改写。`apply_membership` 保留购买快照，但实际额度按 live plan 初始化，防旧订单回写旧额度。CLI 配置同样立即生效。
- `AdminLimits.vue` 使用桌面对照表、手机套餐切换、带范围和当前值的编辑框、仅列变化项的确认页；复用 AdminDialog，限制弹窗高度并内部滚动。QuotaCard 新增可见定时/焦点同步并卸载清理，账户身份隔离继续由 membership store 负责。无需新依赖或数据库表。
- 旧报价冲突时支付弹窗同时刷新金额及权益说明；PLAN_PRICE_CHANGED 兼容错误码保留，提示改为套餐配置更新。价格和会员有效期的购买快照规则不变，时长快照不再用于实际额度计算。

## 2026-11-17 后台改价与报价一致性

- `GET /api/admin/plans` 允许后台管理员读取月卡/年卡；`PATCH /api/admin/plans/{monthly|yearly}/price {price_cents,revision}` 仅超级管理员可写。严格整数分（1–99999999）、版本正整数，拒绝其它字段。
- `admin_store.set_plan_price` 按既有 guard→actor/session 锁后锁套餐，复核当前角色、会话和版本；只更新价格并 revision+1。审计同事务写入 admin_audit_logs，失败回滚；plan 审计目标标签 monthly/yearly，target_id 固定映射 1/2。相同价格不增版本或审计。
- `AdminPricing.vue` 复用后台布局和 AdminDialog，支持校验、二次确认、保存反馈、重试和冲突提示，普通管理员只读。无需新增表或依赖。
- `Pricing.vue` 对可见页面每 30 秒更新，聚焦/可见性变化时更新，打开支付弹窗前复查；合并重叠查询，离页清理监听和定时器。后台更新不移除已有套餐卡。
- `PayModal` 固定展示报价；HTTP 下单新增必填 expected_price_cents、expected_revision，`payments.create_order` 锁套餐后比较报价，变化返回 HTTP 409 / PLAN_PRICE_CHANGED，不创建或复用订单。弹窗刷新金额后须再次点击付款。内部可信调用仍可省略报价，网页 API 不允许省略。
- 订单快照、签名、回调、结算及有效期不变。外部直接调用 `/api/pay/orders` 的客户端也需提供上述必填字段，新前后端一并加载，旧页面请刷新。

## 2026-11-17 月卡价格恢复

- 通过现有本机 CLI `python -m app.membership configure monthly --price-cents 1990 --monthly-seconds 36000` 更新业务配置，monthly revision=3；无需改代码或重启服务。
- 运行中 `/api/plans` 已确认 monthly price_cents=1990、monthly_seconds=36000，功能上限维持 300/10/30/10；free/yearly 配置未变。此次仅配置变更，未创建支付订单或发起付款。

## 2026-11-17 找回密码冷却与入口精简

- `ForgotPasswordForm` 复用 `useVerificationCooldown`，使用独立 password-reset 作用域，避免与注册验证邮件的冷却互相影响。成功申请后开始 60 秒冷却，按钮及 submit 同时拦截重复提交；明确 60 秒限流错误也开始冷却。
- 删除表单 login 事件与返回按钮，移除 AuthModal/PasswordRecovery 上失效的事件监听；重置密码页自身的返回登录链接继续保留。
- `password_recovery_ui.py` 支持 UI_BASE_URL（默认 :5178），本轮对 :8000 已构建前端完成 1440px/390px 模拟 API 验证：60→1→0、Enter 防重复、重发重新计时、返回按钮移除、顶部登录切换、备用找回页、设置新密码及无凭证错误。

## 2026-11-17 登录失败上限调整

- `account_auth.LOGIN_FAILURE_LIMIT=10`，`LOGIN_FAILURE_WINDOW=900` 保持不变；基于邮箱的滚动窗口、成功清除与 IP 独立限流机制不变。
- 离线 `test_login_feedback.py` 对已注册/未知邮箱分别验证前 10 次错误、第 11 次锁定、899 秒仍锁定及 901 秒恢复；通过模拟单调时钟测试，无真实等待或数据库写入。专项验证时独立提高 IP 限流，避免混淆两种限制。

## 2026-11-17 邮件验证冷却展示

- `useVerificationCooldown.js` 为登录/注册提供共享内存邮箱截止时间表；邮箱去空格、小写归一化，按 Date.now 截止时间计算向上取整秒数，避免后台标签页定时器减数漂移。组件卸载清理刷新定时器。
- 发送成功使用接口 resend_after（缺省 60）；EMAIL_SEND_FAILED 与明确 60 秒冷却错误也启动冷却。注册和重发处理函数与按钮共同拦截冷却期重复提交，注册初次提交不受其它邮箱冷却影响。
- `frontend/tests/verification_cooldown_ui.py` 对已构建 :8000 前端模拟全部 API，并推进浏览器时钟检查 60→1→0、按钮禁用、Enter 防重复、重发重置与表单间共享；1440px/390px 通过。登录提示四场景回归通过，未发送真实邮件。

## 2026-11-17 登录失败反馈与注册衔接

- `/api/auth/login` 仍执行密码校验（未知邮箱使用 dummy hash）并累计失败次数；未知邮箱返回 HTTP 401 / `EMAIL_NOT_REGISTERED`，已注册邮箱密码错误返回 HTTP 401 / `INVALID_CREDENTIALS`。限流先于凭证查询，锁定期间保持原提示。
- `LoginForm` 根据错误码显示注册按钮，通过 switch 事件传邮箱；编辑邮箱清除旧提示与邮件验证状态。`AuthModal` 在当前弹窗中切换并向 `RegisterForm.initialEmail` 传入邮箱，保留续作回调；关闭再打开清空预填值。
- 备用 Login 页面跳转 Register 时携带 email 与原 redirect，Register 只读取字符串邮箱作为初值。不传递密码，不自动提交注册或发送邮件。

## 2026-11-16 独立管理后台

- `admin_store.py/admin_auth.py/admin_api.py` 提供 `/api/admin/*` 的独立账号、8 小时会话、权限、注册用户查询和启停、后台账号管理。`freevideo_admin` Cookie 限 `/api/admin`，令牌仅存摘要，后台认证错误使用 `ADMIN_*`，不触发前台退出。
- 新表 `admin_users/admin_sessions/admin_account_guard/admin_audit_logs` 由 schema 与现有初始化入口创建，不插入默认管理员。`python -m app.admin_auth bootstrap --username admin` 只允许首次创建；本机 `reset-password` 可恢复密码，两者均使用 getpass 隐藏输入，不接受密码命令行参数。
- 所有管理写操作按 guard → 按 ID 排序的后台账号行 → 操作者会话 → 注册用户行/会话/邮件凭证顺序加锁，事务内复核最新权限，保障最后一个启用超级管理员。角色变化、密码重置及禁用撤销对应后台会话；审计不含密码、哈希或令牌。
- `users` 增量添加独立的 `status/disabled_at/disabled_reason`，旧账号默认 active。登录及创建会话、邮件验证/恢复在用户锁内复核状态，游客用量认领同样检查；禁用清理所有前台会话与未使用邮件 token。通用会员结算、识别队列和支付入账不按禁用状态中断，保留在途结算与数据。
- 列表每页 20 条，按状态筛选，动态 SQL 仅拼接固定字段并绑定参数；ASCII 邮箱/后台登录名做中文查询时先转 utf8mb4，避免排序规则冲突。所有响应采用字段白名单。
- Vue `src/admin/` 使用独立身份、会话版本与跨标签通道；`App.vue/router.js` 隔离后台布局、守卫及错误重试，前台身份变化不会重建后台。普通管理员无后台账号页面权限；桌面表格、手机卡片，列表查询以 URL 中已应用条件为准，丢弃迟到响应。
- 业务库迁移前后核对既有账号、会员、订单和套餐配置未改变，当前后端已重新加载；首次管理员仍由用户显式初始化。测试使用 `freevideo_admin_test` 与独立的 `freevideo_admin_ui_test:8015`，见 [后台验证](./admin-verification.md)。

## 2026-11-16 本机真实支付测试

- 通过现有 `membership.configure` 将业务库月卡调整为 50 分，保留现有 `monthly_seconds` 和所有功能上限，同时递增 revision；未修改默认种子或支付代码。订单复用同时比较金额和 revision，新下单不会复用旧价订单，旧订单快照不改。
- 本机忽略配置设 `ZPAY_MOCK=false`，后端重新启动加载用户更新的凭证，继续使用 `https://zpayz.cn/submit.php` 和 `http://localhost:8000` 回跳来源。真实凭证不写入文档、前端或版本库。
- 已验证公开套餐接口返回月卡 50 分、支付启用，模拟收银台返回 404；本地签名及金额检查通过，浏览器价格展示和游客登录衔接正常。没有提交真实付款，商户收款能力、结果页入账和会员开通由用户实付验收。

## 2026-11-16 请求会话、分享初始化与分 P 播放

- `account.js` 新增独立会话版本及 `getAuthSessionVersion/handleAuthRequired`，区别于保护身份查询的 `identityGeneration` 和驱动页面重建的 `account.version`。登录、自动登录注册、邮箱验证登录、退出及身份改变递增会话版本；同身份的普通 me/资料更新不递增。
- `accountApi`、`api.request`、ZIP 元信息查询、学习 SSE 与导图请求在发送前捕获会话版本。迟到的 `AUTH_REQUIRED` 仍拒绝原业务请求，但仅在版本仍匹配时清除当前身份。
- 跨标签消息增加 `sessionChanged`，区分会话变动与资料更新；收到会话消息立即使旧错误失效，再查询 me。缺少新字段的旧格式消息按会话变动处理，BroadcastChannel 和 storage 备用通道共用规则。
- `Home.onMounted` 在身份等待前保存操作版本及分享 URL，恢复后先复核版本和组件存活状态，再应用模式与链接。清空显式废弃旧操作；正常分享自动解析与游客降级保持有效。
- 新增纯工具 `learning/videoEmbed.js`，供 `ResultCard` 和 `LearnWorkbench` 构造 B站预览。按 [B站官方播放器参数](https://player.bilibili.com/) 传入 `bvid,p,t,autoplay`，不传会覆盖 `p` 的 `cid`；`p` 仅接受正安全整数，缺省或非法值回第 1 P。解析结果未包含总 P 数，不推断实际选集是否存在。
- 回归包括五个 401 入口、同账号重登、跨标签通知、普通刷新后真实失效、首页延迟初始化，以及两个播放器入口的分 P 跳播。具体结果、复跑命令与人工验收见 [本轮验证记录](./frontend-followup-verification.md)。

## 2026-11-15 支付方式选择

- `PayModal.vue` 使用原生 radio 提供选择语义和键盘焦点，微信项禁用；提交锁同时禁用方式选择。下单传入 `pay_type`，`OrderReq` 当前仅接受 alipay，缺省仍兼容旧请求，未开放方式返回 422。
- 业务层仍由 `payments.PAY_TYPE` 固定支付宝，当前校验字段不是已完成的多通道支付实现；微信接入需同步订单支付类型、复用筛选与网关链路。本站二维码取码及扫码状态区未实现，待用户确认。
- 支付接口专项 14 项通过；1280px／390px 模拟界面检查默认选中、微信禁用、提交字段与下单失败提示通过。二维码流程另待确认，尚未调用获取二维码接口或真实支付。
- 本批界面范围、验证与人工验收见 [前端审查验证记录](./frontend-audit-verification.md)。

## 2026-11-15 桌面导航入口精简

- `NavBar.vue` 桌面游客操作区只保留登录按钮；共用注册表单及账号弹窗注册选项卡继续可用。

## 2026-11-15 精简版额度卡

- 完整额度卡使用白色外卡、浅靛色时长区、双列 AI 用量卡与独立套餐上限行；`sm` 以下单列。用量数字使用 tabular-nums，次数耗尽显示红色反馈；规则改为原生 details 展开。compact 仍沿用简洁摘要。
- 验证：前端构建与现有额度／个人中心两项模拟回归通过；1280px、390px 模拟接口截图检查，无横向溢出。
- `QuotaCard.vue` 的套餐使用上限列表仅在 `!compact` 时渲染。导航桌面／手机菜单均传入 compact；个人中心保留完整显示。
- 原菜单有可视区最大高度与 `overflow-y-auto`，完整详情撑高后会出现滚动条。通过减少菜单内容降低高度，保留矮屏滚动保障操作可达。

## 2026-11-15 账号与首页竞态修复

- `account.js` 为身份查询维护独立 generation。所有 `setUser` 使旧查询失效；迟到成功和错误都不写回。`refresh(true)` 用于跨标签通知，立即发起新查询；旧请求 finally 仅清理自身的 pending 引用。
- 首页 `submitWithView/selectTab` 每次操作递增 `actionVersion`，AI 登录检查与登录续作复核版本；切回下载使先前意图失效。
- `account_store.create_session` 必须接收验密使用的密码哈希；事务内先 `SELECT ... FOR UPDATE` 锁用户，复核密码哈希及邮箱验证状态，再插入会话。改密先完成则登录返回 401；登录先完成则后续改密删除该会话。
- 回归包括迟到游客／旧用户／错误响应、新跨标签查询替代旧查询、首页延迟登录检查后切回下载，以及真实测试库中验密与会话写入之间完成改密或找回重置的交错场景。
- 自动化结果、重跑方式与人工验收见 [账号竞态修复验证](./account-race-verification.md)。部署时需重启后端加载 Python 改动。

## 2026-11-15 找回密码

- `ForgotPasswordForm.vue` 共用于账号弹窗第三选项卡与备用 `/forgot-password` 页面。登录表单在弹窗内仅切换 `authModal.tab='forgot'`，不重置 redirect/onSuccess；独立登录页可打开同一个找回弹窗。发信提示不关闭弹窗，返回登录仅切换选项卡。

- `password_reset.py` 独立编排，复用 SMTP 发信器（主题和正文按找回用途切换），不改下载、会员与支付逻辑。表 `password_resets` 存 user_id、token_hash、credential_hash、created_at、expires_at；凭证绑定当前密码哈希，随账号级联删除。
- `POST /api/auth/forgot-password {email}`：来源检查、IP 和邮箱限速；未知账号不发信，对外响应与已知账号/投递失败一致，避免直接枚举。持久化冷却 60 秒。明确发信失败使本次 token 过期，保留冷却，不自动重试。
- `POST /api/auth/reset-password {token,password}`：先查所属用户，再按用户→token 顺序加锁，与发信一致；校验过期、凭证快照、密码规则，在单个事务中改密、删除全部会话、消费重置链接并清理注册验证链接。并发只成功一次。未验证账号同时激活并以当前时间作为免费周期锚点。
- `PasswordRecovery.vue` 提供 `/forgot-password` 和 `/reset-password` 两个页面；token 只在 hash 传入，进入页面用 Router.replace 清除，只有显式提交新密码才消费，不自动登录。成功后 refresh 同步当前会话，App 对重置页保留实例以展示登出后的成功提示。

## 2026-11-15 注册验证码与登录分离

- `captcha._problem()` 用随机个位数生成加减题，只将算术表达式绘制进 PNG，服务端保存计算结果摘要。输入结果最多两位；图片是带「刷新图形验证码」可访问名称的按钮，支持点击及键盘刷新，刷新清空原答案。

- `CaptchaField` 用关联标签 + 原生数字键盘输入框、固定宽度图片和刷新按钮组成单行；输入框 `min-w-0` 自适应，图片按比例缩放，错误信息在行下方。注册页和弹窗共用。

- `RegisterReq` 仍要求 `captcha_id,captcha_answer`，注册调用一次性校验；`LoginReq` 仅有邮箱密码，登录和重发不读取验证码。不存在关闭注册验证码的配置开关。
- `RegisterForm` 删除昵称、确认密码输入及校验；提交邮箱密码和验证码。待验证状态隐藏图形验证码，重发仅提交邮箱密码。默认昵称由后端从邮箱前缀生成，资料编辑接口不变。
- `LoginForm` 移除验证码组件、取图请求及提交字段；保留登录失败次数限制和重发邮件入口。`AuthModal` 缩减内边距与分区间距。
- 验证：后端 270 项通过，4 个网络测试排除；前端构建与三种窗口初始弹窗无滚动、登录不取验证码、注册等待验证的浏览器检查通过。保留验证码错误/过期/跨浏览器和注册不可绕过的测试。

## 2026-11-15 一次性邮件验证链接

- `email_verification.py` 使用 Python 标准库 SMTP_SSL（可选 STARTTLS）、15 秒超时、校验证书，统一中文错误，不记录授权码、链接或 SMTP 原始响应。QUIT 失败不推翻已确认接受的投递；不自动重发。
- 表 `email_verifications`：用户主键、唯一 SHA256 token 摘要、发送创建时间、过期时间，随账号删除。随机 token 32 字节，30 分钟有效；发送在用户行锁内替换 token，并校验 60 秒冷却，数据库提交后发信。发送失败仅使本次 token 过期，保留冷却；待验证账号可用原密码重发。
- 开启配置时注册调用 `create_user(..., session=None, verified=False)`，不签发 Cookie；发信前检查 SMTP 及可信 PUBLIC_BASE_URL（非本机要求 HTTPS，不采用请求 Host）。禁用配置时保留原自动登录流程。
- `POST /api/auth/resend-verification {email,password,captcha_id,captcha_answer}`：来源、IP 限速、图形验证码、密码校验后重发；不修改密码。`POST /api/auth/verify-email {token}`：原子验证并删除 token、设置邮箱验证状态、更新注册时间和创建会话；并发只成功一次，成功后复用游客认领。
- 链接 `/verify-email#token=...` 的凭证不进入 HTTP URL/访问日志；Vue 页面接收后用 Router.replace 清除 hash，处理同页重复打开，显式按钮 POST 避免邮件扫描自动激活。无凭证刷新需重新打开邮件链接。验证页没有历史任务状态，在 App 身份版本改变时保持该页实例，以呈现切换账号后的成功结果。
- `account.register` 返回待验证结果时不更新登录状态，前端显示收件提示和重发入口；其他标签页验证完成后，现有 BroadcastChannel + me 同步按原规则继续操作。开发模式 :5178 与 localhost:8000 属于不同来源，验收统一使用 localhost:8000。

## 2026-11-15 邮箱认证与图形验证码

- `users` 增加 `email VARCHAR(254) ascii_bin` 唯一键与 `email_verified`（当前默认 1）；启动按列增量迁移，保留内部随机用户名。邮箱只做格式校验与小写规范化，不联网验证，唯一冲突返回 `EMAIL_TAKEN`。
- 注册/登录请求改为 `email,password,captcha_id,captcha_answer`（注册另有可选 nickname）；不接受旧用户名认证。`public_user/me` 增加邮箱及验证状态；注销改为 `password,confirm_email`。本机会员 grant 支持邮箱查找。
- `GET /api/auth/captcha` 返回 `{id,image: data:image/png;base64,...,expires_in:300}`，标准库生成 PNG，无新增依赖。进程内加锁保存浏览器 Cookie 摘要、答案摘要和过期时间；最多 2000 条活动挑战，过期清理，IP 每 10 分钟最多取 60 张。
- 验证码 Cookie 为 HttpOnly、SameSite=Lax、Path=/api，Secure 跟随既有配置。校验时原子弹出挑战，一次消费；错误/过期/重放统一返回 `INVALID_CAPTCHA`，后续认证错误不恢复验证码。进程重启须重新取图，多 worker 需共享存储。
- `CaptchaField.vue` 在共用表单提供图片、换一张、错误与加载反馈；刷新清空答案，卸载丢弃迟到响应。认证成功沿用 `account.js` 同步身份与游客认领。
- 当前注册直接写入已验证状态；未验证状态登录返回 `EMAIL_NOT_VERIFIED`。邮件发送与验证链接尚未实现。

## 2026-11-15 登录弹窗事件保护

- `AuthModal.vue` 用 pointerdown 起点、click 终点与 getBoundingClientRect 判断真正的遮罩点击，替换仅依赖 click.self 的判定，避免内部点击被误认为遮罩。
- 原生 close 事件仅在 dialog 当前已关闭时同步账号弹窗状态；状态 watcher 等待 nextTick 并复核最新状态再调用 showModal/close。
- `task_recovery_ui.py` 补充桌面/390px 登录和注册输入、重定向事件、拖出边界、遮罩、排队关闭事件及登录失败/成功的验证。

## 2026-11-15 异常任务恢复与 AI 计次

- `Home.aiAllowed` 校验操作版本和卸载状态；`AiLearningPanel` 的 ASR 使用独立 AbortController、提交后及轮询后的有效性检查，离页中止查询且不继续创建识别；清空追问中止当前流并丢弃迟到事件。服务器已开始的任务继续执行。
- `pollJob` 对网络与临时服务错误保留原任务状态并重试，对 401/403/404 停止；`streamSSE` 复用 `streamLearnSSE` 统一处理事件格式。
- `AiLearningPanel` 与 `LearnTranscript` 对 SUBMISSION_UNCERTAIN 保留原 ID、说明冻结额度并查询状态；不重发识别。批量恢复监听登录状态，但不改变 `account.js` 的身份隔离清理规则。
- `usage.video_key` 规范化 YouTube 的 watch/shorts/embed/live/youtu.be、B站 BV/av 与分 P、抖音 video/modal_id；其他 URL 排序参数并过滤常见追踪字段，不联网展开短链。
- `ai_usage_videos` 新增 `active_requests` 和 `succeeded`。预占在用户行锁内增加活动计数；各 API 成功调用 `ai_commit`，失败调用 `ai_release`；只有无成功且无活动请求时删除计次。Ticket 本进程终结幂等。启动时按列增量迁移，旧行视作已成功保留；不清空既有账目，进程崩溃中的活动计次保守保留，不自动退回。
- 新增 `task_recovery_ui.py` 覆盖离页、清空对话、身份隔离与同账号批次恢复、SSE 格式、轮询重连、未知识别状态查询；`test_limits.py` 增加视频标识与并发成功/失败交错测试。

## 2026-11-15 功能页登录检查与套餐同步

- `Batch.vue` 监听账号 ID，登录后调用共享 `loadMembership()`；`start` 在提交前等待套餐查询，并检查组件存活、操作版本和账号 ID。查询失败停止提交并显示可重试错误。会员查询沿用共享 pending 去重。
- `Batch.vue`、`AiTools.vue`、`LearnWorkbench.vue` 使用 `checking` 锁定登录检查期间的重复提交，使用同步 watcher 增加操作版本；异步检查和登录成功回调都检查该版本及 `disposed`，防止编辑输入、切换选项或离页后的迟到操作。
- 新增浏览器回归覆盖游客登录后套餐延迟返回、套餐查询失败后重试，以及三个页面在登录状态延迟返回时离页或编辑输入（分别模拟游客及已登录响应）。

## 2026-11-15 功能页浏览与操作鉴权（用户确认保留）

- `router.js` 的 `/batch`、`/ai`、`/learn` 允许游客浏览；`/account`、`/history`、`/pay/result` 保留路由鉴权。
- `Batch.start`、`AiTools.run`、`LearnWorkbench.startParse` 在执行前检查账号状态，通过登录弹窗及成功回调继续操作；回调在组件卸载后不继续操作。
- `BatchSubtitleResults` 挂载时确认已登录后才恢复最近批次，避免游客浏览触发受保护查询。后端接口鉴权不变。
- 以下早期功能页路由鉴权描述以本节为准；已确认并实现的边界修复见上方「功能页登录检查与套餐同步」。

## 2026-11-15 游客额度架构

- `guest.py`：表 `guest_links(subject, link_key, raw_key, duration_seconds, claimed_by, ...)`，`subject` 为 `c:<签名 Cookie id>` 或 `i:<IP>`。Cookie `freevideo_guest`（HttpOnly、SameSite=Lax、Path=/api、10 年，HMAC 复用 `transcription_auth` 的密钥）仅在首次成功解析时下发，伪造或篡改签名视为无 Cookie。
- `/api/parse`（游客）：`begin` 在解析前检查——对 Cookie 与 IP 两个主体，若该链接未记录且主体已有 2 个链接则 403 `GUEST_LIMIT`；解析成功后 `record` 在 MySQL `GET_LOCK` 保护下写入规范化链接及时长，防并发越限。`link_key` 为规范 URL 摘要、`raw_key` 为用户提交 URL 摘要，两者任一命中都视为已知链接。
- `/api/download`（游客）：`require_known` 要求链接已被该游客（Cookie 或 IP）解析过，防止跳过解析直调下载。登录用户路径不变。`/api/subtitles`、`/api/transcript`、`/api/transcriptions`（POST）对游客统一返回 401 `AUTH_REQUIRED`；批量与 AI 原本已强制登录。
- 并入额度：`account_api.register/login` 成功后调用 `guest.claim`，仅处理 Cookie 主体且 `claimed_by IS NULL` 的行：在用户行锁内把时长合计加到当前周期 `used_seconds`（上限为剩余额度），再标记已认领；响应带 `guest_claimed_seconds`，前端 `account.js` 弹出提示。认领失败只记日志，不影响登录。
- 前端：`Home.parse` 遇到 `GUEST_LIMIT` 自动 `openAuth`，登录后继续解析；`ResultCard` 下载遇到同码也弹登录窗；`TranscriptPanel` 对游客只显示登录提示（不请求字幕），登录后通过 `account.loggedIn` 监听自动开始。首页徽标、FAQ、定价 FAQ、移动升级条、升级弹窗同步为新规则。
- 测试：`tests/test_guest.py`（8 项：2 个名额、清 Cookie、不同 IP 独立、先解析才能下载及其它功能 401、登录用户不受限、认领一次、认领封顶、伪造 Cookie）；`test_membership.py` 中游客字幕用例改为 401；`ui_regression.py` 增加游客登录提示与名额用完弹窗；`membership_ui.py` 的游客识别用例改为先点登录提示。


## 2026-11-15 套餐使用上限架构

- **配置**：`membership_plans` 增加 `ai_monthly_limit / batch_max_links / asr_max_minutes / chat_daily_limit`。`account_store.init_schema` 在列不存在时 ALTER 添加并按 `DEFAULT_LIMITS` 回填（仅首次迁移，不覆盖已调整的数值）；`membership.seed` 的新库默认值同源。上限按当前套餐代码实时读取（`membership.limits(user_id)`），不像时长额度那样快照到 `user_memberships`。
- **AI 计次**（`usage.py`）：表 `ai_usage_videos(user_id, period, video_key)`，`period` 与 `user_quota_periods` 同键，`video_key` 为 URL 的 sha256；`ai_begin` 在用户行锁内判断，已计过的视频直接放行，否则按套餐上限计数后插入，超限抛 `AccountError(AI_QUOTA_EXCEEDED, 403)`；`ai_release` 在未产生任何输出时删除本次新增行。`ai_learning_api` 的 `/summary`、`/chat` 在首个 delta 出现后才算已消费（`keep`），`/mindmap` 在成功返回后保留；旧 `/api/ai/summary`、`/api/ai/translate` 同样接入（翻译作业失败时释放）。
- **追问每日限额**：表 `ai_chat_daily(user_id, day, used)`，`day` 为北京时间日期，`chat_begin` 原子递增并校验，失败时 `chat_release` 退回。追问先过视频计次、再过每日限额，任一失败都释放已占用部分。
- **批量**：`main.batch_cap(user_id)` 返回 `min(套餐条数, MAX_BATCH)`；`/api/batch` 超限返回 403 `BATCH_LIMIT`，`BatchTranscriptionManager.submit(owner, texts, max_links, plan_name)` 超限抛同码 `TranscriptionError`；无登录用户信息的旧测试路径回退到 `MAX_BATCH`。
- **识别时长**：`transcriptions.max_seconds(uid)` 取 `min(套餐分钟*60, ASR_MAX_DURATION)`；`_run` 在解析时长后和音轨获取后各校验，抛 `AUDIO_TOO_LONG`（提示套餐上限）。`probe_audio` 仍使用全局硬上限，保持原测试语义。
- **摘要接口**：`membership.summary` 增加 `ai_limit / ai_used / chat_daily_limit / chat_used_today / batch_max_links / asr_max_minutes`；`/api/plans` 因 `SELECT *` 自动带上四个上限列。
- **前端**：`QuotaCard` 展示本期 AI 视频、今日追问、批量与识别时长；`Pricing` 套餐卡与对比表读取 `plan.*` 上限；`Batch` 的条数上限取 `membership.data.batch_max_links`（受 `/api/health.max_batch` 限制），超限在提交前提示并链接定价页；`AiLearningPanel` / `TranscriptPanel` / `Batch` 的识别时长提示优先用账号套餐值；AI 面板在每次生成结束后刷新额度。
- **测试**：`tests/test_limits.py`（10 项，真实 MySQL 测试库，含迁移回填、计次/释放/重置周期、追问日切、批量与时长）；`ui_regression.py` 增加定价/额度卡展示、批量超限拦截、AI 超限提示。`account_ui.py` 的设备列表选择器改为最近的 `section`，避免统计额度卡新增的 `li`。


## 2026-11-15 前端审查与优化实现

- `NavBar.vue`：移除 PRO 角标、桌面右上角「升级 Pro」按钮、手机菜单底部「查看会员套餐」按钮与下拉中重复的「个人中心」项；Esc 同时关闭桌面下拉与手机菜单并把焦点还给触发按钮；点击导航外区域关闭手机菜单。外部点击判断使用 `event.composedPath()`，因为菜单开关会替换图标节点，`contains(event.target)` 会把导航内点击误判为外部。
- `ResultCard.vue`：头部下载按钮负责「合并中 / 下载中」状态，卡片内只留「复制链接」；`coverOnly` 计算属性区分真实图集与封面兜底；无音频预览地址时显示提示；移除与 `allow="fullscreen"` 冲突的 `allowfullscreen`。
- `AiTools.vue` / `api.js`：`streamSSE` 增加可选 `signal`；总结加提交锁、卸载中止、复制失败提示；Tab 增加 `tablist/tab/aria-selected`。
- `Home.vue`：模式选项卡增加 `id` 与 `aria-controls`，结果区为 `role="tabpanel"`；占位符缩短避免手机端截断；去掉 PRO 徽标后手机端两个选项卡同行。
- `Batch.vue` / `AiLearningPanel.vue`：挂载时读取 `/api/health.asr_max_minutes`，不再写死 60 分钟。
- `router.js` + `pages/NotFound.vue`：未知路径渲染 404 页（`notFound` 路由名，标题已登记）。
- `Account.vue`：默认分区为 `membership`（`?section=` 仍可指定），分区说明移入对应卡片内。`History.vue` 改用 `hero-bg`。
- 删除 `style.css` 的 `.pro-badge`；`data.js` 的 `pro` 字段与平台画质表述同步修正。
- 测试：`ui_regression.py` 新增文案规则、AI 复制失败、Esc 与账号菜单、结果卡去重、404、个人中心默认分区共 6 项（含手机菜单开启后保持可见）；`account_ui.py` 依赖默认「基本资料」的用例改为 `?section=profile`。

## 2026-11-13 识别异常的展示与诊断

- 修复 `asr_flash` 完整性判断：`usage.duration` 是句尾报告的处理用量，不应要求等于本地音轨时长；HTTP 流正常读完、末句 final、累计文本与最终句/词时间轴一致后返回成功。尾部仅含用量的事件不覆盖末句状态；读取异常、未结束句和空响应仍失败并保留原预占保护。依据：[官方 Flash HTTP API](https://help.aliyun.com/en/model-studio/fun-asr-flash-recorded-speech-recognition-http-api)。
- 本地复现、离线回放、回归测试与已有任务恢复记录见 [ASR 修复验证](./asr-flash-verification.md)。供应商成本与用户额度独立核算；修复代码不自动重发旧任务或修改未决流水。
- `TranscriptPanel` 按 `SUBMISSION_UNCERTAIN` 统一展示通俗标题与说明，兼容已保存的旧错误文本；「查看处理状态」只查询现有任务，直接 HTTP 识别的未决请求仍需管理员核对，不能承诺自动恢复。
- `transcriptions` 记录任务 ID、错误码、传输类型与不确定标记；`asr_flash` 记录 HTTP 状态、异常类型、受限服务错误码和完整性指标。日志不写凭证、音频、正文或原始响应体，保留原扣量与防重复提交规则。

## 2026-11-13 账号菜单身份入口

- `NavBar.vue` 复用共享 `membership.data`，将桌面下拉框和手机账号卡改为原生 `RouterLink` 个人中心入口，整行可点、支持键盘焦点，点击后主动收起菜单（包括已在个人中心时）。
- 顶部显示首字母头像、昵称/用户名及右箭头；按用户最终选择恢复浅靛色卡片、原文字颜色，下方根据 `plan` 显示灰色「普通用户」或浅金色皇冠「PRO 用户」标签。未取得会员状态时显示加载/不可用文案，不用默认免费身份代替真实状态。

## 2026-11-13 个人周期与单一套餐额度

- `membership.period(anchor, now)` 按北京时间从原始时间锚点推导 `[start,end)`；免费锚点为 `users.created_at`，Pro 为 `user_memberships.starts_at`，保留时分秒和微秒，短月不造成后续日期漂移。无需定时清零，首次查询或预占新周期时幂等创建额度记录。
- `user_quota_periods.period`、`quota_reservations.period` 改为 `VARCHAR(40)`；键为 `free:<UTC周期起点>` 或 `pro:<UTC周期起点>`。任一时刻只提供当前套餐额度，前缀用于隔离历史账目，不代表两个可同时消费的余额。`account_store.init_schema` 仅将旧 `CHAR(7)` 扩宽，保留旧周期的结算能力；不搬迁旧自然月用量。
- 查询、预占共用一次事务内捕获的时间和用户行锁，避免边界计算不一致；结算继续使用预占记录的周期键。跨周期未决预占仍减少当前可用量，原有去重、幂等和失败释放保持有效。
- `apply_membership` 首次开通建立新的 Pro 周期；同档续费、升级均保留原开通锚点和当前 Pro 已用/预占。升级提高当前上限；支付有效期的剩余时长顺延规则保留。`renewal_expiry` 对原周年边界上的月底续费从原锚点计算，避免 1/31 → 2/28 后续费漂移至 3/28。
- `/api/account/membership` 保留总额度/已用/预占/可用字段，`period_start/resets_at` 使用 UTC ISO 时间；新增 `period_end`、`reset_basis=registration|membership`、`ends_with_membership`。会员到期前最后一期结束时间截断至 `expires_at`，前端标为会员到期，而非承诺再次重置 Pro 额度。
- `QuotaCard` 单余额、单进度条，日期区仅保留一行「下次重置」（会员最后一期为「会员到期」），时间精确到分钟，移除本期开始和重复的规则说明；完整规则留在 `Pricing`、`UpgradeModal` 和 `PayModal`。测试与人工验收见 [个人周期额度验收](./anniversary-quota-verification.md)。以下早期自然月架构记录以本节为准。

## 2026-11-13 ZPAY 支付架构

- `zpay.py`：协议薄封装——`sign_string/sign/verify`（排序、排除 sign/sign_type/空值、不编码、`md5(...+KEY)` 小写）、`money/cents`（整数分 ↔ 两位小数）、`submit_form` 生成 submit.php 表单字段（notify_url=`PUBLIC_BASE_URL/api/pay/notify`，return_url=`PUBLIC_BASE_URL/pay/result`）、`query_order`（`api.php?act=order`，3 秒超时，异常抛 `ZpayError`，不记录含 KEY 的 URL）、`refund`。`enabled()` = 配置了 PID+KEY 或模拟模式；`mock_active()` 在 `SESSION_SECURE=true` 时恒为 False。
- `payments.py`：`create_order`（登录用户、10 分钟 10 次限速、锁用户行、规则判定 `outcome()`、复用 TTL 内同价未支付订单、26 位数字单号）、`fulfil`（锁用户行 → 锁订单行；非 pending 直接返回；金额/交易号冲突写 `conflict` 事件不入账；按 new/renew/upgrade 调用 `membership.apply_membership`，refused 或用户已删除标记 `refund_required`）、`confirm`（查单 → fulfil）、`handle_notify`（验签+pid+TRADE_SUCCESS+金额+类型，再 confirm；返回 `success`/`fail`）、`order_status`（本人订单，pending 时最多每 5 秒查单一次，原子 `last_checked_at` 抢占）、`reconcile` + `Reconciler` 线程（lifespan 启停，24 小时内 pending，每轮 20 条），CLI `orders/sync/refund`。
- `membership.py` 抽出 `months_after()`（北京时间按日历月加、月底截断）与 `apply_membership()`（写权益快照并替换本月额度上限，保留已用/预占），`grant` 与支付共用；`summary/plans` 的 `payment_enabled` 动态返回。
- `payment_api.py`：`POST /api/pay/orders {plan}` → `{order, action, fields, preview}`；`GET /api/pay/orders`（最近 20 笔）；`GET /api/pay/orders/{no}`；`GET|POST /api/pay/notify`（无登录与来源校验，纯文本）。`zpay_mock.py`：`/api/pay/mock/submit.php`（验签后渲染模拟收银台）、`/pay`（成功/不发通知/重复通知/取消，通知在线程池中经 HTTP 发往 notify_url）、`/api.php?act=order`；非模拟模式全部 404。表单体手工解析，不引入 python-multipart。
- 表 `payment_orders`（套餐快照、status `pending|paid|refund_required|refunded`、`trade_no` 唯一、`fulfilment`、`membership_expires_at`、`last_checked_at`，`user_id` 外键 ON DELETE SET NULL）与 `payment_events`（create/fulfil/conflict/refund 流水，去除 sign/key）。
- 前端：`payment.js`（`purchaseKind` 与后端规则一致、`submitToGateway` 动态表单 POST、sessionStorage 记住单号）、`PayModal.vue`（原生 dialog，提交锁）、`Pricing.vue`（开通/续费/升级/禁用文案，游客登录后继续）、`PayResult.vue`（`/pay/result`，2 秒轮询最多 2 分钟）、`Account.vue` 会员分区「我的订单」，支持 `/account?section=membership`。
- 测试：`tests/test_payments.py`（13 项，含 10 线程并发只入账一次）、`frontend/tests/payment_ui.py`（真实后端 + 模拟收银台）。配置与运维见 [zpay-setup.md](./zpay-setup.md)。

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
| `.text-gold` / `.btn-gold` | 金橙色系，用于会员/付费元素（与主色区分，形成转化焦点） |
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
