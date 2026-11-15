<script setup>
import { computed, onUnmounted, onWatcherCleanup, ref, watch } from 'vue'
import LearnIcon from './LearnIcon.vue'
import { formatTs, parseTs } from './learnApi.js'
import { api, transcriptionFileUrl, triggerDownload } from '../api.js'

const props = defineProps({
  info: { type: Object, required: true },
  externalResult: { type: Object, default: null },
})
const emit = defineEmits(['result', 'seek', 'notify'])

const language = ref('')
const result = ref(null)
const job = ref(null)
const busy = ref(false)
const error = ref('')
const errorCode = ref('')
const keyword = ref('')
const asrEnabled = ref(null)

let abortCtrl = null
let pollTimer = null

const sourceLabel = computed(() => ({
  platform_subtitle: '平台字幕',
  automatic_subtitle: '自动字幕',
  asr: '语音转写',
}[result.value?.source] || ''))

const parsedLines = computed(() => {
  const timed = result.value?.timed_text || ''
  if (!timed) return []
  return timed.split(/\r?\n/).filter(Boolean).map((raw, idx) => {
    const m = raw.match(/^\s*\[([^\]]+)\]\s*(.*)$/)
    if (m) {
      const sec = parseTs(m[1])
      return { id: idx, sec, ts: sec !== null ? formatTs(sec) : m[1], text: m[2] }
    }
    return { id: idx, sec: null, ts: '', text: raw }
  })
})

const filteredLines = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return parsedLines.value
  return parsedLines.value.filter((item) => item.text.toLowerCase().includes(q) || item.ts.includes(q))
})

const canManualAsr = computed(() => ['NO_SUBTITLES', 'EMPTY_SUBTITLES', 'ASR_REQUIRED'].includes(errorCode.value))

function stopPending() {
  abortCtrl?.abort()
  abortCtrl = null
  clearTimeout(pollTimer)
  busy.value = false
}

function accept(val) {
  result.value = val
  emit('result', val)
}

async function loadPlatformSubtitles() {
  stopPending()
  const ctrl = new AbortController()
  abortCtrl = ctrl
  busy.value = true
  error.value = ''
  errorCode.value = ''
  accept(null)

  try {
    const res = await api.transcript({ url: props.info.url, lang: language.value || null }, ctrl.signal)
    if (abortCtrl === ctrl) accept(res)
  } catch (e) {
    if (e.name === 'AbortError' || abortCtrl !== ctrl) return
    error.value = e.message
    errorCode.value = e.code || 'SUBTITLE_FAILED'
  } finally {
    if (abortCtrl === ctrl) busy.value = false
  }
}

async function startManualTranscribe() {
  if (busy.value) return
  stopPending()
  const ctrl = new AbortController()
  abortCtrl = ctrl
  busy.value = true
  error.value = ''
  errorCode.value = ''

  const poll = async (id) => {
    if (abortCtrl !== ctrl) return
    try {
      const state = await api.transcription(id, ctrl.signal)
      if (abortCtrl !== ctrl) return
      job.value = state
      if (state.status === 'done') {
        accept(state.result)
        busy.value = false
        return
      }
      if (state.status === 'error') {
        error.value = state.error
        errorCode.value = state.error_code || 'ASR_ERROR'
        busy.value = false
        return
      }
      pollTimer = setTimeout(() => poll(id), 1500)
    } catch (e) {
      if (e.name === 'AbortError' || abortCtrl !== ctrl) return
      if (e.status === 404 || e.status === 403) {
        error.value = e.message
        busy.value = false
      } else {
        pollTimer = setTimeout(() => poll(id), 3500)
      }
    }
  }

  try {
    await api.transcriptionSession()
    if (abortCtrl !== ctrl) return
    if (job.value?.error_code === 'SUBMISSION_UNCERTAIN') { await poll(job.value.id); return }
    const created = await api.transcribe({ url: props.info.url, lang: language.value || null, allow_asr: true }, ctrl.signal)
    if (abortCtrl !== ctrl) return
    job.value = created
    await poll(created.id)
  } catch (e) {
    if (e.name !== 'AbortError') {
      error.value = e.message
      errorCode.value = e.code || 'REQUEST_FAILED'
      busy.value = false
    }
  }
}

function downloadSub(fmt) {
  if (!result.value) return
  if (job.value?.status === 'done') {
    triggerDownload(transcriptionFileUrl(job.value.id, fmt))
    return
  }
  const content = fmt === 'srt' ? result.value.srt : result.value.text
  const safe = (props.info.title || '视频文稿').replace(/[\\/:*?"<>|\r\n]+/g, '_').slice(0, 70)
  const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
  triggerDownload(url, `${safe}.${fmt}`)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

async function copyAll() {
  if (!result.value?.text) return
  try {
    await navigator.clipboard.writeText(result.value.text)
    emit('notify', '完整文稿已复制')
  } catch {
    emit('notify', '复制失败，请手动复制', 'error')
  }
}

watch(() => props.externalResult, (val) => {
  if (val && val !== result.value) {
    result.value = val
    error.value = ''
    errorCode.value = ''
  }
})

watch(() => props.info, (info) => {
  stopPending()
  keyword.value = ''
  job.value = null
  error.value = ''
  errorCode.value = ''
  accept(null)
  if (!info) return

  language.value = info.default_subtitle || info.subtitles?.[0]?.lang || ''
  api.health().then((h) => { asrEnabled.value = h.asr_enabled }).catch(() => {})

  if (info.subtitles?.length) {
    loadPlatformSubtitles()
  } else {
    errorCode.value = 'NO_SUBTITLES'
    error.value = info.subtitle_notice || '该视频暂无平台字幕，可点击下方按钮或右侧面板确认后提取语音文稿。'
  }
  onWatcherCleanup(() => stopPending())
}, { immediate: true })

onUnmounted(stopPending)
</script>

<template>
  <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-bold text-slate-900 sm:text-base">带时间轴逐字稿</h3>
        <span v-if="result" class="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700">
          {{ sourceLabel }} · {{ result.cues }} 句
        </span>
      </div>

      <div class="flex flex-wrap items-center gap-1.5 text-xs">
        <select v-if="info.subtitles?.length > 1" v-model="language" aria-label="选择字幕语言"
          class="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-700"
          @change="loadPlatformSubtitles">
          <option v-for="s in info.subtitles" :key="s.lang" :value="s.lang">{{ s.name }}</option>
        </select>
        <template v-if="result">
          <button type="button" class="btn-ghost h-8 px-2.5 font-medium" @click="copyAll">复制</button>
          <button type="button" class="btn-ghost h-8 px-2.5 font-medium" @click="downloadSub('srt')">SRT</button>
          <button type="button" class="btn-ghost h-8 px-2.5 font-medium" @click="downloadSub('txt')">TXT</button>
        </template>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="busy" class="mt-3 flex items-center gap-2 rounded-xl bg-indigo-50 p-3 text-xs text-indigo-800">
      <LearnIcon name="loader" :size="15" class="shrink-0 animate-spin" />
      <span>{{ job?.message || '正在读取视频字幕…' }}</span>
    </div>

    <!-- Error / No Subtitles Notice -->
    <div v-if="error && !busy && !result" class="mt-3 rounded-xl bg-slate-50 p-3.5 text-xs leading-5 text-slate-600">
      <template v-if="errorCode === 'SUBMISSION_UNCERTAIN'"><p>暂时无法取得识别结果。本次时长暂时冻结，尚未结算，请稍后查看状态或联系管理员，请勿重复提交。</p><button type="button" class="btn-ghost mt-2 min-h-11 px-3" @click="startManualTranscribe">查看处理状态</button></template>
      <p v-else>{{ error }}</p>
      <button v-if="canManualAsr" type="button" :disabled="asrEnabled === false"
        class="btn-primary mt-2.5 inline-flex h-9 items-center gap-1.5 rounded-xl px-3.5 text-xs font-semibold"
        @click="startManualTranscribe">
        <LearnIcon name="sparkles" :size="14" /> 确认语音转文字（消耗识别额度）
      </button>
    </div>

    <!-- Searchable Timestamped Lines -->
    <template v-if="result">
      <div class="relative mt-3">
        <LearnIcon name="search" :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input v-model="keyword" type="text" placeholder="搜索逐字稿关键词快速定位…"
          class="input-control w-full rounded-xl py-2 pl-8 pr-8 text-xs" />
        <button v-if="keyword" type="button" class="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600"
          @click="keyword = ''">清空</button>
      </div>

      <div class="mt-2.5 max-h-[340px] space-y-1 overflow-y-auto pr-1 text-xs leading-6">
        <div v-if="!filteredLines.length" class="py-6 text-center text-slate-400">未找到包含「{{ keyword }}」的台词</div>
        <div v-for="line in filteredLines" :key="line.id"
          class="group flex items-start gap-2 rounded-lg px-2 py-1 transition hover:bg-indigo-50/60">
          <button v-if="line.sec !== null" type="button"
            class="mt-0.5 shrink-0 rounded bg-indigo-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-indigo-600 transition group-hover:bg-indigo-600 group-hover:text-white"
            @click="emit('seek', line.sec)">
            {{ line.ts }}
          </button>
          <span class="text-slate-700">{{ line.text }}</span>
        </div>
      </div>
    </template>
  </div>
</template>
