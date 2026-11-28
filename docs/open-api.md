# 视频文案提取开放 API v1

在线文档：`/account/api/docs`；密钥管理：`/account/api`；独立 OpenAPI Schema：`GET /api/openapi.json`。

## 权限、额度与密钥

- 有效月卡、年卡会员可以创建密钥、提交新任务，API 沿用现有套餐价格，不另收按次费用；免费账号可阅读文档。
- 与网站共用所属账号的 ASR 时长、个人周期及单条识别上限。平台字幕免费；显式允许 ASR 后，符合无字幕/空字幕条件才调用识别，网络或权限错误不自动回退。
- 用户用量按实际音轨秒数向上取整预占，成功结算，明确失败释放，状态不明保留预占。查询、导出、复用结果不再次扣量，不增加 AI 总结计次。
- 每账号最多 3 把有效密钥。完整随机凭证仅在创建响应中返回一次，数据库只存 SHA-256 摘要。网站退出不撤销密钥；改密、找回重置、账号禁用会撤销密钥，重新启用不恢复旧凭证。
- 会员到期不能创建新密钥、新任务，但有效密钥仍可查询、导出已受理任务至保留期结束。撤销密钥或禁用账号会拒绝所有后续调用，已受理任务仍继续处理和结算。
- 网站 Cookie 仅用于管理密钥，不能作为开放接口凭据。有效密钥可查询同账号通过 API 登记的任务，不能枚举纯网页历史任务。注销账号级联清除密钥与 API 授权。

## 基础协议

Base URL：`https://你的实际域名/api/open/v1`。本机：`http://127.0.0.1:8000/api/open/v1`。

请求头：`Authorization: Bearer fv_live_...`。长期密钥只存服务端环境变量，不放 URL、前端、小程序包或公开仓库。线上使用 HTTPS；本次实现不自动配置证书和微信侧通信域名。

所有响应 no-store，带 `X-Request-ID`。JSON 成功包装为 `{request_id,data}`，请求错误为 `{request_id,error:{code,message,retryable}}`。文件导出成功直接返回正文。

## 提交任务

`POST /transcriptions`，JSON 请求体，必填请求头 `Idempotency-Key`。

```json
{
  "url": "https://www.douyin.com/video/作品ID",
  "allow_asr": true,
  "lang": null
}
```

| 参数 | 规则 |
|---|---|
| url | 必填，1–2000 字符，可传分享文本，取首个 http(s) URL |
| allow_asr | 严格布尔值，默认 false；true 表示授权该请求在无可用字幕时使用识别额度 |
| lang | null 或 1–32 位字母、数字、下划线、连字符；只选字幕轨道，不翻译，不强制识别语言 |
| Idempotency-Key | 请求头，1–128 位 `[A-Za-z0-9_.:-]`；首次请求前生成并持久化 |

拒绝额外参数，不接受客户端 user_id、owner、时长或内部任务 ID。

首版开放现有抖音、B站、YouTube 视频路径。YouTube 依赖部署网络；不新增小红书、快手、直播、图集、合集或任意媒体 URL 提交能力。短链仅展开 v.douyin.com/b23.tv，每跳检查域名和公网 DNS 地址；最终重建包含视频 ID、必要分 P 的平台 URL，去除任意跳转参数。第三方适配器后续网络请求仍需部署出站限制配合，入口校验不替代全部网络防护。

成功返回 HTTP 202，data 为任务对象，即使很快完成也保持 202。同账号、同键、同提取 URL/语言/ASR 参数返回原 API 任务；同键不同参数返回 HTTP 409。分享文本移除后不计入摘要，剩余 URL 查询参数仍参与摘要。短链仅在新接收时展开，原键重试不再次联网展开。

幂等记录最多保留 30 天。已过期但尚未清理的键返回 IDEMPOTENCY_EXPIRED；清理后原键不保证复用，新工作使用新键。网络超时、断线或 503 后先沿用原键和参数。请求级错误可能已经登记幂等记录，重复提交会返回同一已失败任务；禁止自动生成新键重新识别。

## 查询与结果

`GET /transcriptions/{task_id}`。建议每 3–5 秒查询，设置最大等待；到时保存 task_id，之后继续查询。HTTP 200 表示查询成功，不表示视频处理成功。

| status | 处理方式 |
|---|---|
| queued / running | 排队 / 处理中，继续查询原任务 |
| succeeded | 读取 result 或导出文稿 |
| failed | 检查 error.code/message/retryable，禁止无条件重提 |
| uncertain | 识别或结算待核对、时长暂时冻结；只查原任务或联系管理员，不重发音轨 |

| 字段 | 含义 |
|---|---|
| task_id | API 任务 ID，与内部转写 ID 分开 |
| status / stage / message | 状态枚举、当前阶段、中文说明 |
| title / platform | 标题、平台，可为 null |
| source_url | 原作品页面地址，可为 null |
| video_url | 可取得的视频播放/下载直链，可为 null |
| cover_url | 封面图片地址，可为 null |
| duration_seconds | 视频时长秒数，可为 null |
| created_at / expires_at | UTC ISO 时间，复用不会延长旧结果有效期 |
| media_notice | 媒体地址有效期说明 |
| result | 成功时为文稿对象，否则 null |
| error | 失败/待核对时为 code/message/retryable 对象，否则 null |

result 示例：

```json
{
  "text": "你好，这里是口播原文。",
  "timed_text": "[00:00] 你好，这里是口播原文。",
  "srt": "1\n00:00:00,000 --> 00:00:02,000\n你好，这里是口播原文。\n",
  "cue_count": 1,
  "source": "asr",
  "language": null
}
```

source 为 `platform_subtitle|automatic_subtitle|asr`；language 为实际报告的语言，不猜测。提取内容是字幕/语音原文，不包含 OCR、改写或 AI 总结。

**媒体地址说明**：video_url 和 cover_url 来自平台，可能过期、受防盗链、地区或客户端限制。30 天任务保留期不代表媒体地址有效 30 天。YouTube 当前不返回视频直链；其他平台无适用地址时也返回 null，不用网页地址冒充直链。本站不托管视频、不承诺永久有效或小程序一定可播。重复查询不刷新地址、不触发新 ASR；旧历史结果没有这些元信息时也可能为 null。

## 导出与额度

- `GET /transcriptions/{task_id}/file?format=txt|srt`：默认 txt，必须已成功；UTF-8 正文、中文文件名，未完成时 HTTP 409。需要密钥，不提供无鉴权公开文件 URL。
- `GET /quota`：返回 `{request_id,data}`；data 含 `plan,limit_seconds,used_seconds,reserved_seconds,pending_previous_seconds,available_seconds,resets_at,asr_max_minutes`。系统硬上限仍可能低于套餐上限。

## 限流与错误

按账号：提交 10 次/分钟；查询、额度、导出合计 60 次/分钟；最多 2 个活动 API 提取任务（含排队，别名按实际目标统计）。全站仍受 ASR_WORKERS + ASR_MAX_QUEUE 限制。同一来源 IP 的凭据认证另限 180 次/分钟。多把密钥不会增加账号额度或限流名额。429 返回 `Retry-After: 60`。

| HTTP | code 示例 | 含义 |
|---|---|---|
| 401 | API_KEY_INVALID | 密钥缺失、无效、撤销或账号不可用 |
| 403 | API_MEMBERSHIP_REQUIRED | 会员权限不足 |
| 404 | NOT_FOUND | 任务不存在、过期或无该 API 任务授权 |
| 409 | IDEMPOTENCY_CONFLICT / IDEMPOTENCY_EXPIRED / RESULT_NOT_READY | 参数冲突、旧键过期、文稿未完成 |
| 422 | INVALID_REQUEST / INVALID_IDEMPOTENCY_KEY / UNSUPPORTED_URL / UNSAFE_URL | 参数、链接或地址不符合要求 |
| 429 | RATE_LIMIT / API_CONCURRENCY_LIMIT / QUEUE_FULL | 频率或容量超限 |
| 503 | RECOVERING / DB_UNAVAILABLE / SERVICE_UNAVAILABLE | 恢复中或暂不可用 |

异步错误放在任务 error 中，例如 ASR_REQUIRED、QUOTA_EXCEEDED、AUDIO_TOO_LONG、ASR_DISABLED、NO_SPEECH、PARTIAL_RECOGNITION、SUBMISSION_UNCERTAIN、INTERRUPTED，不把查询 HTTP 状态改为 403/503。平台字幕可在 ASR 时长耗尽时继续免费提取。

单进程内存队列不跨重启续跑；已保存结果和媒体信息可以从数据库恢复。未提交任务中断且不扣用户时长；状态不明的云请求保留预占且不自动重发。API 授权在入队前持久化，进程中断后的恢复只核对记录，不重新提交音轨。

## 示例与小程序

- [Python 标准库示例](../frontend/public/examples/freevideo_open_api.py)
- [Node.js 22+ 内置 fetch 示例](../frontend/public/examples/freevideo_open_api.mjs)

设置 FREEVIDEO_BASE_URL、FREEVIDEO_API_KEY、FREEVIDEO_URL、首次请求前保存的 FREEVIDEO_IDEMPOTENCY_KEY 后运行。默认不调用 ASR；设置 FREEVIDEO_ALLOW_ASR=true 才授权。设置 FREEVIDEO_TASK_ID 跳过创建、恢复查询。临时错误沿用原键重试，不跟随重定向转发凭据，轮询约 5 分钟后停止等待并保留任务 ID。

小程序通过自己的服务端/云函数调用；应用方负责其微信用户认证、查询归属、消费授权、业务限额和长期密钥。本次不包含小程序 UI、微信登录和云函数部署。真实域名、HTTPS、微信侧通信配置和媒体播放限制在发布联调时验证。
