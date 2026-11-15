<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { api, transcriptionFileUrl, triggerDownload } from '../api.js'
import Icon from './Icon.vue'
import { account, openAuth } from '../account.js'
import { loadMembership, membership } from '../membership.js'

const props = defineProps({
  info: { type: Object, required: true },
  active: { type: Boolean, default: true },
  externalResult: { type: Object, default: null },
})
const emit = defineEmits(['result', 'notify', 'update:timestamps'])
const language = ref('')
const result = ref(null)
const job = ref(null)
const busy = ref(false)
const error = ref('')
const errorCode = ref('')
const retryable = ref(false)
const timestamps = ref(false)
const asrEnabled = ref(null)
const healthMinutes = ref(60)
const maxMinutes = computed(() => membership.data?.asr_max_minutes || healthMinutes.value)
const reconnect = ref(false)
const auto = ref(false)
const guestPrompt = ref(false)
let healthReady = Promise.resolve()
let version = 0
let controller
let timer

const text = computed(() => timestamps.value ? result.value?.timed_text : result.value?.text)
const canTranscribe = computed(() => ['NO_SUBTITLES', 'EMPTY_SUBTITLES', 'ASR_REQUIRED'].includes(errorCode.value))
const awaitingResult = computed(() => errorCode.value === 'SUBMISSION_UNCERTAIN')
const sourceLabel = computed(() => ({ platform_subtitle: '平台字幕', automatic_subtitle: '平台自动字幕', asr: '语音转写' }[result.value?.source] || ''))
const phaseLabel = computed(() => ({ queued: '排队', subtitles: '检查字幕', audio: '获取音轨', upload: '上传音频', recognizing: '语音识别', export: '生成字幕' }[job.value?.stage] || '提取字幕'))

function resetRequest() {
  version++
  controller?.abort()
  clearTimeout(timer)
  controller = new AbortController()
  return version
}

function accept(value) {
  result.value = value
  emit('result', value)
}

async function loadSubtitles() {
  const current = resetRequest()
  busy.value = true
  error.value = ''
  errorCode.value = ''
  job.value = null
  reconnect.value = false
  accept(null)
  try {
    const value = await api.transcript({ url: props.info.url, lang: language.value || null }, controller.signal)
    if (current === version) accept(value)
  } catch (e) {
    if (current !== version || e.name === 'AbortError') return
    error.value = e.message
    errorCode.value = e.code || 'SUBTITLE_FAILED'
    retryable.value = true
  } finally {
    if (current === version) busy.value = false
  }
  await autoTranscribe(current)
}

// Only a confirmed "no / empty subtitles" result starts speech recognition; network or auth failures never do.
// When hidden in AI Summary view (active === false), defer automatic paid ASR to user confirmation in AiLearningPanel.
async function autoTranscribe(current) {
  if (!props.active) return
  if (current !== version || !['NO_SUBTITLES', 'EMPTY_SUBTITLES'].includes(errorCode.value)) return
  await healthReady
  if (current !== version || !props.active || asrEnabled.value === false) return
  auto.value = true
  await transcribe()
}

async function poll(id, current) {
  if (current !== version) return
  try {
    const value = await api.transcription(id, controller.signal)
    if (current !== version) return
    job.value = value
    reconnect.value = false
    error.value = ''
    if (value.status === 'done') {
      loadMembership()
      accept(value.result)
      busy.value = false
      return
    }
    if (value.status === 'error') {
      loadMembership()
      error.value = value.error
      errorCode.value = value.error_code
      retryable.value = value.retryable
      busy.value = false
      return
    }
    timer = setTimeout(() => poll(id, current), 1500)
  } catch (e) {
    if (current !== version || e.name === 'AbortError') return
    error.value = e.message
    if (e.status === 404 || e.status === 403) {
      busy.value = false
      reconnect.value = false
      errorCode.value = 'EXPIRED'
    } else {
      // A lost poll is not a failed paid task. Resume querying the SAME id.
      reconnect.value = true
      timer = setTimeout(() => poll(id, current), 4000)
    }
  }
}

async function transcribe() {
  if (busy.value) return
  if (!account.loggedIn) {
    await account.ensure()
    if (!account.loggedIn) {
      const expected = version
      openAuth({ notice: '登录后可使用每月免费语音识别额度', onSuccess: () => { if (expected === version && props.active) transcribe() } })
      return
    }
  }
  const current = resetRequest()
  busy.value = true
  error.value = ''
  errorCode.value = ''
  reconnect.value = false
  try {
    // Establish the cookie before a potentially ambiguous paid POST response.
    await api.transcriptionSession()
    if (current !== version) return
    const value = await api.transcribe({ url: props.info.url, lang: language.value || null, allow_asr: true }, controller.signal)
    if (current !== version) return
    job.value = value
    await poll(value.id, current)
  } catch (e) {
    if (current !== version || e.name === 'AbortError') return
    error.value = e.message
    errorCode.value = e.code || 'REQUEST_FAILED'
    retryable.value = e.retryable !== false
    busy.value = false
  }
}

function exportFile(format) {
  if (!result.value) return
  if (job.value?.status === 'done') {
    triggerDownload(transcriptionFileUrl(job.value.id, format))
    return
  }
  const content = format === 'srt' ? result.value.srt : result.value.text
  const name = (props.info.title || '视频文稿').replace(/[\\/:*?"<>|\r\n]/g, '_').slice(0, 80)
  const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
  triggerDownload(url, `${name}.${format}`)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

async function copy() {
  try {
    await navigator.clipboard.writeText(text.value || '')
    emit('notify', '文稿已复制')
  } catch {
    emit('notify', '复制失败，请手动选择文稿复制', 'error')
  }
}

watch(() => props.externalResult, (val) => {
  if (val && val !== result.value) {
    resetRequest()
    busy.value = false
    error.value = ''
    errorCode.value = ''
    accept(val)
  }
})

watch(() => props.active, async (isActive) => {
  if (isActive && !result.value && !busy.value && !job.value && ['NO_SUBTITLES', 'EMPTY_SUBTITLES'].includes(errorCode.value)) {
    await autoTranscribe(version)
  }
})

watch(timestamps, (val) => {
  emit('update:timestamps', val)
})

async function init(info) {
  resetRequest()
  busy.value = false
  job.value = null
  error.value = ''
  errorCode.value = ''
  timestamps.value = false
  accept(null)
  auto.value = false
  language.value = info.default_subtitle || info.subtitles?.[0]?.lang || ''
  healthReady = api.health().then((health) => {
    if (props.info === info) {
      asrEnabled.value = health.asr_enabled
      healthMinutes.value = health.asr_max_minutes || 60
    }
  }).catch(() => { if (props.info === info) asrEnabled.value = null })
  // Guests may only download; subtitle and speech-to-text features need an account.
  if (!account.loggedIn) await account.ensure()
  if (props.info !== info) return
  guestPrompt.value = !account.loggedIn
  if (guestPrompt.value) return
  if (info.subtitles?.length) await loadSubtitles()
  else {
    const current = version
    errorCode.value = 'NO_SUBTITLES'
    error.value = info.subtitle_notice || '未提取到可下载字幕，可从视频声音生成文字。'
    await autoTranscribe(current)
  }
}
watch(() => props.info, init, { immediate: true })
watch(() => account.loggedIn, (loggedIn) => { if (loggedIn && guestPrompt.value) init(props.info) })

loadMembership()
onUnmounted(resetRequest)
</script>

<template>
  <section class="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm sm:p-5" aria-label="视频文稿">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-wrap items-center gap-2">
        <h4 class="text-lg font-semibold text-gray-800">视频文案</h4>
        <span v-if="result" class="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700">{{ sourceLabel }} · {{ result.cues }} 条</span>
      </div>
      <label v-if="info.subtitles?.length > 1" class="flex items-center gap-2 text-sm text-gray-600">
        字幕语言
        <select v-model="language" class="input-control min-h-11 rounded-xl px-3" @change="loadSubtitles">
          <option v-for="s in info.subtitles" :key="s.lang" :value="s.lang">{{ s.name }}</option>
        </select>
      </label>
    </div>

    <div v-if="guestPrompt" class="mt-4 rounded-xl bg-indigo-50 p-4 text-sm leading-6 text-indigo-900" role="status">
      <p class="font-semibold">登录后可提取平台字幕与视频文稿</p>
      <p class="mt-1">游客可免费下载 2 个视频；字幕提取、语音转文字、批量提取与 AI 总结需要登录，登录后下载不限次数。</p>
      <button type="button" class="btn-primary mt-3 inline-flex min-h-11 items-center gap-2 rounded-xl px-4 font-semibold"
        @click="openAuth({ notice: '登录后即可提取字幕与视频文稿' })">登录 / 注册</button>
    </div>

    <div v-if="busy" class="mt-4 rounded-xl bg-indigo-50 p-4 text-sm text-indigo-800" role="status" aria-live="polite">
      <div class="flex items-center gap-2 font-semibold">
        <Icon name="loader" :size="18" class="animate-spin motion-reduce:animate-none" />
        {{ reconnect ? '正在恢复任务查询' : phaseLabel }}
      </div>
      <p class="mt-2 leading-6">{{ reconnect ? '网络连接中断，正在继续查询原任务，不会重复提交识别。' : (job?.message || (auto ? '未找到可用字幕，已自动从视频声音生成文字…' : '正在提取平台字幕…')) }}</p>
      <p v-if="auto && job" class="mt-2 text-xs leading-5 text-indigo-700">未找到可用字幕，已自动从视频声音生成文字；音频将发送至云端识别，最长 {{ maxMinutes }} 分钟。</p>
      <p v-if="job" class="mt-2 text-xs leading-5 text-indigo-700">切换页面会停止查询；已提交的任务会继续处理。</p>
    </div>

    <div v-if="error && !busy" class="mt-4 rounded-xl p-4 text-sm leading-6"
      :class="canTranscribe ? 'bg-slate-50 text-slate-600' : 'bg-rose-50 text-rose-700'" :role="canTranscribe ? 'status' : 'alert'">
      <template v-if="awaitingResult">
        <p class="font-semibold">暂时无法取得识别结果</p>
        <p class="mt-1">本次识别时长已暂时冻结，尚未结算。请勿重复提交，可稍后查看状态或联系管理员处理。</p>
      </template>
      <p v-else>{{ error }}</p>
      <template v-if="canTranscribe">
        <p class="mt-2 text-xs leading-5">音频将发送至云端识别，最长 {{ maxMinutes }} 分钟。识别原语音，不自动翻译或润色。</p>
        <button type="button" class="btn-primary mt-3 inline-flex min-h-11 items-center gap-2 rounded-xl px-4 font-semibold"
          :disabled="asrEnabled === false" @click="transcribe">
          <Icon name="file" :size="16" />音频转文字
        </button>
        <p v-if="asrEnabled === false" class="mt-2 text-xs">音频转文字尚未启用，请联系管理员配置服务。</p>
      </template>
      <button v-else-if="errorCode === 'SUBMISSION_UNCERTAIN' && job" type="button"
        class="mt-3 min-h-11 rounded-xl border border-rose-200 bg-white px-4 font-semibold"
        @click="busy = true; poll(job.id, version)">查看处理状态</button>
      <button v-else-if="retryable" type="button" class="mt-3 min-h-11 rounded-xl border border-rose-200 bg-white px-4 font-semibold"
        @click="job || errorCode === 'REQUEST_FAILED' ? transcribe() : loadSubtitles()">重试</button>
    </div>

    <template v-if="result">
      <div class="mt-4 flex flex-wrap gap-2">
        <button type="button" class="btn-ghost min-h-11 rounded-xl px-3 text-sm" :aria-pressed="timestamps" @click="timestamps = !timestamps">{{ timestamps ? '切换纯文本' : '显示时间戳' }}</button>
        <button type="button" class="btn-ghost min-h-11 rounded-xl px-3 text-sm" @click="copy">复制文稿</button>
        <button type="button" class="btn-ghost min-h-11 rounded-xl px-3 text-sm" @click="exportFile('txt')">下载 TXT</button>
        <button type="button" class="btn-ghost min-h-11 rounded-xl px-3 text-sm" @click="exportFile('srt')">下载 SRT</button>
      </div>
      <p class="mt-3 max-h-[32rem] overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-gray-50 p-4 text-sm leading-7 text-gray-800">{{ text }}</p>
    </template>
  </section>
</template>
