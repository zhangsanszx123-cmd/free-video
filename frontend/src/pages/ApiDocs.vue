<script setup>
import { ref } from 'vue'
const base = window.location.origin + '/api/open/v1'
const copied = ref('')
const endpoints = [
  ['POST', '/transcriptions', '创建任务', '202'],
  ['GET', '/transcriptions/{task_id}', '查询状态与结果', '200'],
  ['GET', '/transcriptions/{task_id}/file?format=txt|srt', '导出文稿', '200'],
  ['GET', '/quota', '查询共享识别额度', '200'],
]
const fields = [
  ['task_id', 'string', 'API 任务 ID。保存后可跨设备查询，不能传入网页任务 ID。'],
  ['status', 'string', 'queued / running / succeeded / failed / uncertain'],
  ['stage / message', 'string', '当前处理阶段及中文说明。'],
  ['title / platform', 'string | null', '作品标题、平台标识。'],
  ['source_url', 'string | null', '原作品页面链接。'],
  ['video_url', 'string | null', '平台提供的可播放/下载视频直链，无法取得时为 null。'],
  ['cover_url', 'string | null', '封面图片地址，无法取得时为 null。'],
  ['duration_seconds', 'number | null', '视频时长，单位秒。'],
  ['created_at / expires_at', 'string', 'UTC ISO 时间。任务最多保留 30 天，复用旧结果时以旧结果到期时间为准。'],
  ['result.text', 'string', '口播原文；不是作品简介、OCR、AI 改写或总结。'],
  ['result.timed_text / srt', 'string', '带时间戳的原文 / 完整 SRT。'],
  ['result.cue_count', 'integer', '字幕条数，不是逐句数组。'],
  ['result.source', 'string', 'platform_subtitle / automatic_subtitle / asr'],
  ['result.language', 'string | null', '字幕或识别服务报告的语言，无法确定时为 null。'],
  ['error', 'object | null', 'code / message / retryable；仅失败或待核对时返回。'],
]
const codes = [
  ['401', 'API_KEY_INVALID', '密钥缺失、无效、已撤销或账号不可用'],
  ['403', 'API_MEMBERSHIP_REQUIRED / QUOTA_EXCEEDED', '会员权限或共享识别额度不足'],
  ['404', 'NOT_FOUND', '任务不属于该账号的 API 请求，或任务已过期'],
  ['409', 'IDEMPOTENCY_CONFLICT / RESULT_NOT_READY', '幂等键参数冲突 / 文稿尚未生成'],
  ['422', 'INVALID_REQUEST / UNSUPPORTED_URL', '参数类型、长度或视频链接不符合要求'],
  ['429', 'RATE_LIMIT / API_CONCURRENCY_LIMIT / QUEUE_FULL', '请求频率或任务容量超限，遵循 Retry-After'],
  ['503', 'RECOVERING / SERVICE_UNAVAILABLE', '服务恢复中或暂不可用，查询原任务'],
]
const snippets = [
  { id: 'auth', title: '1. 设置服务端环境变量', text: `export FREEVIDEO_BASE_URL='${base}'\nexport FREEVIDEO_API_KEY='你的完整密钥'` },
  { id: 'create', title: '2. 提交任务（cURL）', text: `curl -X POST "$FREEVIDEO_BASE_URL/transcriptions" \\\n  -H "Authorization: Bearer $FREEVIDEO_API_KEY" \\\n  -H 'Content-Type: application/json' \\\n  -H 'Idempotency-Key: order-20261128-001' \\\n  -d '{"url":"https://www.douyin.com/video/作品ID","allow_asr":true}'` },
  { id: 'query', title: '3. 使用返回的 task_id 查询', text: `curl "$FREEVIDEO_BASE_URL/transcriptions/你的task_id" \\\n  -H "Authorization: Bearer $FREEVIDEO_API_KEY"` },
  { id: 'result', title: '成功结果示例', text: JSON.stringify({ request_id: '本次请求追踪标识', data: { task_id: '保存这个任务ID', status: 'succeeded', stage: 'done', message: '提取完成', title: '示例视频', platform: 'Douyin', source_url: 'https://www.douyin.com/video/作品ID', video_url: 'https://cdn.example.com/video.mp4', cover_url: 'https://cdn.example.com/cover.jpg', duration_seconds: 120, created_at: '2026-11-28T04:00:00+00:00', expires_at: '2026-12-28T04:00:00+00:00', result: { text: '你好，这里是口播原文。', timed_text: '[00:00] 你好，这里是口播原文。', srt: '1\n00:00:00,000 --> 00:00:02,000\n你好，这里是口播原文。\n', cue_count: 1, source: 'asr', language: null }, error: null, media_notice: '平台临时地址可能过期，无法获取时为 null。' } }, null, 2) },
  { id: 'error', title: '请求错误示例', text: JSON.stringify({ request_id: '本次请求追踪标识', error: { code: 'IDEMPOTENCY_CONFLICT', message: '同一幂等键不能用于不同请求参数', retryable: false } }, null, 2) },
]
async function copy(item) {
  try { await navigator.clipboard.writeText(item.text); copied.value = item.id }
  catch { copied.value = 'failed' }
}
</script>

<template>
  <section class="hero-bg min-h-screen px-4 py-8 sm:py-12">
    <div class="mx-auto max-w-6xl">
      <header class="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div><p class="text-sm font-bold tracking-widest text-indigo-600">FREEVIDEO · OPEN API V1</p><h1 class="mt-3 text-3xl font-extrabold tracking-tight text-slate-950 sm:text-4xl">视频文案提取 API</h1><p class="mt-4 max-w-2xl text-sm leading-7 text-slate-600">从公开作品链接获取口播原文、时间轴、视频与封面地址。使用异步任务，让你的服务端轻松接入。</p></div>
        <RouterLink to="/account/api" class="btn-primary inline-flex min-h-12 items-center justify-center rounded-xl px-6 text-sm font-semibold">创建与管理密钥 →</RouterLink>
      </header>
      <div class="grid items-start gap-6 lg:grid-cols-[190px_minmax(0,1fr)]">
        <nav aria-label="API 文档目录" class="flex flex-wrap gap-1 rounded-2xl border border-slate-200 bg-white p-3 lg:sticky lg:top-24 lg:flex-col">
          <a v-for="item in [['start','快速接入'],['contract','接口与参数'],['media','视频与封面地址'],['states','状态与错误'],['quota','权限与计费'],['examples','示例与小程序']]" :key="item[0]" :href="'#' + item[0]" class="flex min-h-11 items-center rounded-xl px-3 text-sm font-semibold text-slate-600 hover:bg-indigo-50 hover:text-indigo-700">{{ item[1] }}</a>
        </nav>
        <div class="min-w-0 space-y-6">
          <section id="start" class="glass-card scroll-mt-24 rounded-3xl p-5 sm:p-8">
            <h2 class="text-xl font-bold text-slate-950">快速接入</h2><p class="mt-3 text-sm leading-7 text-slate-600">有效月卡、年卡会员可创建密钥。文档公开阅读。首版支持现有抖音、B站解析能力，YouTube 取决于服务器网络与平台限制；暂不支持小红书、快手、图文或直播。</p>
            <p class="mt-4 text-xs font-bold uppercase tracking-widest text-slate-500">Base URL</p><code class="mt-2 block break-all rounded-xl bg-indigo-50 p-4 text-sm text-indigo-900">{{ base }}</code>
            <p class="mt-3 text-sm leading-7 text-slate-600">线上使用 HTTPS，凭证放在 <code>Authorization: Bearer &lt;API Key&gt;</code> 请求头。网站登录 Cookie 不可代替 API 密钥。</p>
            <div v-for="item in snippets.slice(0,3)" :key="item.id" class="mt-5 min-w-0"><div class="mb-2 flex items-center justify-between gap-2"><h3 class="text-sm font-bold text-slate-800">{{ item.title }}</h3><button class="min-h-11 shrink-0 rounded-lg px-3 text-sm font-semibold text-indigo-600 hover:bg-indigo-50" @click="copy(item)">{{ copied === item.id ? '已复制' : '复制' }}</button></div><pre class="overflow-x-auto rounded-2xl bg-slate-950 p-4 text-xs leading-7 text-slate-100 sm:text-sm"><code>{{ item.text }}</code></pre></div>
            <p class="mt-4 text-sm leading-7 text-slate-600">提交成功返回 HTTP 202。每隔 3–5 秒查询一次，直到 succeeded、failed 或 uncertain。等待超时只停止轮询并保存 task_id，之后继续查询原任务。</p>
          </section>
          <section id="contract" class="glass-card scroll-mt-24 rounded-3xl p-5 sm:p-8">
            <div class="flex flex-wrap items-center justify-between gap-3"><h2 class="text-xl font-bold text-slate-950">接口与参数</h2><a href="/api/openapi.json" target="_blank" rel="noopener" class="inline-flex min-h-11 items-center text-sm font-semibold text-indigo-600 hover:underline">查看 OpenAPI Schema ↗</a></div>
            <div class="mt-5 space-y-3"><div v-for="ep in endpoints" :key="ep[1]" class="rounded-xl border border-slate-200 p-4"><div class="flex items-center gap-2"><span class="rounded-md px-2 py-1 font-mono text-xs font-bold" :class="ep[0] === 'POST' ? 'bg-indigo-100 text-indigo-800' : 'bg-emerald-50 text-emerald-800'">{{ ep[0] }}</span><span class="text-sm font-semibold text-slate-800">{{ ep[2] }}</span><span class="ml-auto text-xs text-slate-500">{{ ep[3] }}</span></div><code class="mt-2 block break-all text-xs leading-6 text-slate-700">{{ ep[1] }}</code></div></div>
            <h3 class="mt-6 font-bold text-slate-900">创建请求</h3><ul class="mt-3 space-y-2 text-sm leading-7 text-slate-600"><li><code>url</code>：必填字符串，最长 2000 字符，可粘贴分享文本，提取首个链接。</li><li><code>allow_asr</code>：布尔值，默认 false。true 表示明确允许无可用字幕时消耗账号额度进行语音识别。访问受限或网络错误不会自动转为收费识别。</li><li><code>lang</code>：可选字幕语言，例如 zh-Hans。仅选择轨道，不翻译，不强制识别语言。</li><li><code>Idempotency-Key</code>：必填请求头，1–128 位字母、数字或 <code>_.:-</code>。发送前生成并持久化；网络超时重试沿用同一键和参数。</li></ul>
            <p class="mt-3 rounded-xl bg-indigo-50 p-4 text-sm leading-7 text-indigo-900">同账号、同键、同参数返回原任务；同键不同参数返回 409。记录保留最多 30 天，过期不保证复用。请求级错误时原键可能已被受理，可先用原键查询提交结果；明确失败后按错误提示决定是否使用新键重试。</p>
            <h3 class="mt-6 font-bold text-slate-900">查询响应字段</h3><dl class="mt-3 divide-y divide-slate-100"><div v-for="field in fields" :key="field[0]" class="py-3"><dt class="flex flex-wrap items-center gap-2"><code class="break-all text-sm font-semibold text-slate-900">{{ field[0] }}</code><span class="font-mono text-xs text-slate-500">{{ field[1] }}</span></dt><dd class="mt-1 text-sm leading-7 text-slate-600">{{ field[2] }}</dd></div></dl>
          </section>
          <section id="media" class="scroll-mt-24 rounded-3xl border border-amber-200 bg-amber-50 p-5 sm:p-8"><h2 class="text-xl font-bold text-amber-950">视频与封面地址说明</h2><p class="mt-3 text-sm leading-7 text-amber-950">video_url 是播放/下载直链，source_url 是原作品页面，两者用途不同。平台无法提供适用直链时 video_url 为 null；YouTube 当前不返回视频直链。封面缺失时 cover_url 为 null。</p><p class="mt-3 text-sm leading-7 text-amber-950">这些地址由源平台提供，可能过期或受防盗链、地区及客户端环境限制。任务保留 30 天不代表媒体地址有效 30 天。本站不托管视频、不承诺固定有效时长；反复查询任务不会刷新地址或重新识别。小程序播放前应自行处理失败和源平台限制。</p></section>
          <section id="states" class="glass-card scroll-mt-24 rounded-3xl p-5 sm:p-8"><h2 class="text-xl font-bold text-slate-950">状态与错误</h2><dl class="mt-4 space-y-3 text-sm leading-7"><div v-for="item in [['queued / running','已排队 / 处理中，继续查询原任务。'],['succeeded','已完成，读取 result 或下载 TXT/SRT。'],['failed','处理失败，查看 error.code 和 retryable；不要无条件自动重提。'],['uncertain','识别或结算状态待核对，时长暂时冻结。只查询原任务或联系管理员，禁止重复提交音轨。']]" :key="item[0]"><dt class="font-mono font-semibold text-slate-900">{{ item[0] }}</dt><dd class="text-slate-600">{{ item[1] }}</dd></div></dl>
            <p class="mt-4 text-sm leading-7 text-slate-600">任务处理失败与请求失败分开：查询到 failed/uncertain 仍返回 HTTP 200。服务重启不自动续跑或重发收费识别；已保存结果可继续读取。</p>
            <div class="mt-5 space-y-3"><div v-for="code in codes" :key="code[0]" class="rounded-xl bg-slate-50 p-4"><div class="flex flex-wrap gap-2"><span class="font-mono text-sm font-bold text-indigo-700">{{ code[0] }}</span><code class="break-all text-xs leading-6 text-slate-800">{{ code[1] }}</code></div><p class="mt-1 text-sm leading-6 text-slate-600">{{ code[2] }}</p></div></div>
            <div v-for="item in snippets.slice(3)" :key="item.id" class="mt-5"><h3 class="mb-3 text-sm font-bold text-slate-900">{{ item.title }}</h3><pre class="max-h-[36rem] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-7 text-slate-100"><code>{{ item.text }}</code></pre></div>
          </section>
          <section id="quota" class="glass-card scroll-mt-24 rounded-3xl p-5 sm:p-8"><h2 class="text-xl font-bold text-slate-950">权限与计费</h2><ul class="mt-3 space-y-2 text-sm leading-7 text-slate-600"><li>API 和网站共用所属账号的识别时长、个人周期及单条识别上限。平台字幕免费；ASR 按实际音轨秒数向上取整预占，成功结算，明确失败释放，状态不明保留预占。</li><li>查询、导出和复用已有结果不再次扣量。不同密钥共用额度；本接口不产生 AI 总结计次，不另收 API 按次费用。</li><li>提交每账号每分钟最多 10 次；查询、额度和导出合计每分钟最多 60 次；每账号最多 2 个活动 API 任务，仍受全站队列容量约束。达到限制返回 429 和 Retry-After。</li><li>会员到期后禁止创建新密钥和新任务，已有有效密钥可查询、导出已受理任务至保留期结束。相同幂等键的原任务仍可查询。</li><li>密钥撤销、改密、找回重置或账号禁用后不能继续调用，已受理任务继续处理和结算。账号注销删除相关密钥与任务授权。</li><li>结果保留最多 30 天。短期音轨清理不影响已保存的文字；隐藏网页历史不增加开放 API 对其他任务的访问权限。</li></ul></section>
          <section id="examples" class="glass-card scroll-mt-24 rounded-3xl p-5 sm:p-8"><h2 class="text-xl font-bold text-slate-950">调用示例与小程序</h2><div class="mt-4 flex flex-wrap gap-3"><a href="/examples/freevideo_open_api.py" download class="btn-ghost inline-flex min-h-11 items-center px-4 text-sm font-semibold">下载 Python 示例</a><a href="/examples/freevideo_open_api.mjs" download class="btn-ghost inline-flex min-h-11 items-center px-4 text-sm font-semibold">下载 Node.js 示例</a></div><p class="mt-4 text-sm leading-7 text-slate-600">示例使用标准库或内置 fetch，无需额外依赖。设置 FREEVIDEO_BASE_URL、FREEVIDEO_API_KEY、FREEVIDEO_URL、FREEVIDEO_IDEMPOTENCY_KEY 后运行；可用 FREEVIDEO_TASK_ID 恢复查询。默认只读平台字幕，设置 FREEVIDEO_ALLOW_ASR=true 才允许识别扣量。</p><p class="mt-4 rounded-xl bg-slate-50 p-4 text-sm leading-7 text-slate-700">推荐调用链：小程序 → 你自己的服务端或云函数 → FreeVideo API。服务端负责微信用户认证、任务查询权限、消费控制和密钥保管。不要把长期密钥放进小程序包、前端存储或 wx.request 示例。第三方应用同样从服务端调用。</p></section>
          <p v-if="copied === 'failed'" role="status" class="text-sm text-amber-800">无法自动复制，请选中代码手动复制。</p>
        </div>
      </div>
    </div>
  </section>
</template>
