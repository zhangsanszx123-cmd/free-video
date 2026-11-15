<script setup>
import { computed, nextTick, onMounted, onUnmounted, onWatcherCleanup, reactive, ref, useTemplateRef, watch } from 'vue'
import './learning.css'
import LearnIcon from './LearnIcon.vue'
import MindMapView from './MindMapView.vue'
import { extractSuggestions, formatTs, learnApi, platformTimeUrl } from './learnApi.js'
import { renderLearningMarkdown } from './markdown.js'
import { api, triggerDownload } from '../api.js'
import { loadMembership, membership } from '../membership.js'

const props = defineProps({
  info: { type: Object, default: null },
  transcript: { type: String, default: '' },
  externalSeek: { type: Boolean, default: false },
  workbenchMode: { type: Boolean, default: false },
  autoRunTrigger: { type: Number, default: 0 },
})
const emit = defineEmits(['seek', 'notify', 'transcribed'])

const rootEl = useTemplateRef('panel-root')
const chatListEl = useTemplateRef('chat-list')

const activeTab = ref('summary')
const mode = ref('general')
const aiEnabled = ref(true)
const healthAsrMinutes = ref(60)
const asrMaxMinutes = computed(() => membership.data?.asr_max_minutes || healthAsrMinutes.value)

const summaries = reactive({ general: '', study: '', deep: '' })
const summaryMeta = ref(null)
const summaryLoading = ref(false)
const summaryStatus = ref('')
const summaryError = ref('')

const mindmapMd = ref('')
const mindmapLoading = ref(false)
const mindmapError = ref('')

const chatMessages = ref([])
const chatInput = ref('')
const chatLoading = ref(false)
const chatError = ref('')

const needAsr = ref(null)
const asrBusy = ref(false)
const asrMessage = ref('')
const localTranscript = ref('')
const localTranscriptionId = ref('')
const internalToast = ref('')

let summaryAbort = null
let mindmapAbort = null
let chatAbort = null
let asrPollTimer = null
let toastTimer = null

const MODES = [
  { id: 'general', label: '通用精读', desc: '主旨 · 要点 · 章节时间轴 · 术语' },
  { id: 'study', label: '课堂笔记', desc: '知识框架 · 步骤公式 · 自测问答' },
  { id: 'deep', label: '深度拆解', desc: '核心论点 · 论证脉络 · 案例洞察' },
]

const DEFAULT_QUESTIONS = [
  '请用通俗语言提炼视频最核心的 3 个结论',
  '视频中提到了哪些关键方法、案例或实操步骤？',
  '帮我梳理整支视频前后的逻辑递进关系',
]

const currentSummary = computed(() => summaries[mode.value] || '')
const summaryHtml = computed(() => renderLearningMarkdown(currentSummary.value))
const effectiveTranscript = computed(() => (props.transcript || localTranscript.value || '').trim())
const hasTranscriptReady = computed(() => effectiveTranscript.value.length > 0)

const suggestedQuestions = computed(() => {
  const fromMode = extractSuggestions(currentSummary.value || summaries.general || summaries.study || summaries.deep)
  return fromMode.length ? fromMode : DEFAULT_QUESTIONS
})

const sourceLabel = computed(() => {
  const src = summaryMeta.value?.source
  const map = {
    loaded_transcript: '已加载文稿（免二次提取）',
    platform_subtitle: '平台原生字幕',
    automatic_subtitle: '平台自动字幕',
    asr: '云端语音转写',
  }
  return map[src] || ''
})

function notify(msg, type = 'success') {
  emit('notify', msg, type)
  if (!props.workbenchMode) return
  clearTimeout(toastTimer)
  internalToast.value = msg
  toastTimer = setTimeout(() => { internalToast.value = '' }, 2400)
}

function abortAll() {
  summaryAbort?.abort()
  mindmapAbort?.abort()
  chatAbort?.abort()
  summaryAbort = null
  mindmapAbort = null
  chatAbort = null
  clearTimeout(asrPollTimer)
  summaryLoading.value = false
  mindmapLoading.value = false
  chatLoading.value = false
  asrBusy.value = false
}

function resetState() {
  abortAll()
  summaries.general = ''
  summaries.study = ''
  summaries.deep = ''
  summaryMeta.value = null
  summaryStatus.value = ''
  summaryError.value = ''
  mindmapMd.value = ''
  mindmapError.value = ''
  chatMessages.value = []
  chatInput.value = ''
  chatError.value = ''
  needAsr.value = null
  asrMessage.value = ''
  localTranscript.value = ''
  localTranscriptionId.value = ''
}

watch(() => props.info?.url, () => {
  resetState()
  onWatcherCleanup(() => abortAll())
})

watch(() => props.transcript, (val) => {
  if (val && val.trim() && needAsr.value) {
    needAsr.value = null
  }
})

let lastHandledTrigger = 0
watch(
  () => [props.autoRunTrigger, props.info?.url],
  ([trig, url]) => {
    if (trig > 0 && trig !== lastHandledTrigger && url) {
      lastHandledTrigger = trig
      nextTick(() => {
        if (!summaryLoading.value && !summaries[mode.value]) {
          runSummary(false)
        }
      })
    }
  },
  { immediate: true },
)

onMounted(async () => {
  loadMembership()
  try {
    const h = await api.health()
    aiEnabled.value = Boolean(h.ai_enabled)
    healthAsrMinutes.value = h.asr_max_minutes || 60
  } catch { /* ignore */ }
})

onUnmounted(() => {
  abortAll()
  clearTimeout(toastTimer)
})

function handleSeek(seconds) {
  if (props.externalSeek) {
    emit('seek', seconds)
    return
  }
  const host = rootEl.value?.parentElement
  const videoEl = host?.querySelector('video')
  if (videoEl && videoEl.getAttribute('src')) {
    videoEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
    videoEl.currentTime = seconds
    videoEl.play?.().catch(() => {})
    notify(`已跳转至视频 ${formatTs(seconds)}`)
    return
  }
  const audioEl = host?.querySelector('audio')
  if (audioEl && audioEl.getAttribute('src')) {
    audioEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
    audioEl.currentTime = seconds
    audioEl.play?.().catch(() => {})
    notify(`已跳转至音频 ${formatTs(seconds)}`)
    return
  }
  if (props.info?.url) {
    const targetUrl = platformTimeUrl(props.info.url, seconds)
    window.open(targetUrl, '_blank', 'noopener')
    notify(`已在原平台打开 ${formatTs(seconds)} 处`)
  }
}

function onProseClick(e) {
  const btn = e.target.closest?.('[data-seek]')
  if (!btn) return
  const sec = Number(btn.getAttribute('data-seek'))
  if (Number.isFinite(sec)) handleSeek(sec)
}

async function runSummary(force = false) {
  if (!props.info?.url || summaryLoading.value || asrBusy.value) return
  if (!force && summaries[mode.value]) return

  summaryAbort?.abort()
  const ctrl = new AbortController()
  summaryAbort = ctrl

  activeTab.value = 'summary'
  const targetMode = mode.value
  summaries[targetMode] = ''
  summaryError.value = ''
  needAsr.value = null
  summaryLoading.value = true
  summaryStatus.value = hasTranscriptReady.value ? 'AI 正在阅读文稿…' : '正在检查视频字幕…'

  try {
    await learnApi.summary(
      {
        url: props.info.url,
        mode: targetMode,
        title: props.info.title || null,
        transcript: effectiveTranscript.value || null,
        transcription_id: localTranscriptionId.value || null,
      },
      (event, data) => {
        if (event === 'status') summaryStatus.value = String(data || '')
        else if (event === 'meta') summaryMeta.value = data
        else if (event === 'delta') summaries[targetMode] += String(data || '')
        else if (event === 'need_asr') needAsr.value = { ...(data || {}), nextAction: 'summary' }
        else if (event === 'error') summaryError.value = String(data || '总结失败')
      },
      ctrl.signal,
    )
  } catch (e) {
    if (e.name !== 'AbortError') summaryError.value = e.message || 'AI 总结请求失败'
  } finally {
    if (summaryAbort === ctrl) {
      summaryLoading.value = false
      summaryStatus.value = ''
      loadMembership()
    }
  }
}

function selectMode(nextMode) {
  if (mode.value === nextMode) return
  mode.value = nextMode
  if (!summaries[nextMode] && (summaries.general || summaries.study || summaries.deep)) {
    runSummary(true)
  }
}

async function runMindmap(force = false) {
  if (!props.info?.url || mindmapLoading.value || asrBusy.value) return
  if (!force && mindmapMd.value) return

  mindmapAbort?.abort()
  const ctrl = new AbortController()
  mindmapAbort = ctrl

  activeTab.value = 'mindmap'
  mindmapLoading.value = true
  mindmapError.value = ''
  needAsr.value = null

  const anySummary = currentSummary.value || summaries.general || summaries.study || summaries.deep
  try {
    const res = await learnApi.mindmap(
      {
        url: props.info.url,
        title: props.info.title || null,
        transcript: effectiveTranscript.value || null,
        summary: anySummary || null,
        transcription_id: localTranscriptionId.value || null,
      },
      ctrl.signal,
    )
    mindmapMd.value = res.markdown || ''
  } catch (e) {
    if (e.name === 'AbortError') return
    if (e.code === 'NEED_ASR') {
      needAsr.value = { message: e.message, asr_enabled: e.asrEnabled !== false, nextAction: 'mindmap' }
    } else {
      mindmapError.value = e.message || '生成思维导图失败'
    }
  } finally {
    if (mindmapAbort === ctrl) {
      mindmapLoading.value = false
      loadMembership()
    }
  }
}

function switchTab(tab) {
  activeTab.value = tab
  if (tab === 'mindmap' && !mindmapMd.value && (hasTranscriptReady.value || currentSummary.value)) {
    runMindmap(false)
  }
}

async function sendChat(prefill = '') {
  const question = (typeof prefill === 'string' && prefill ? prefill : chatInput.value).trim()
  if (!question || !props.info?.url || chatLoading.value || asrBusy.value) return

  chatAbort?.abort()
  const ctrl = new AbortController()
  chatAbort = ctrl

  activeTab.value = 'chat'
  chatError.value = ''
  needAsr.value = null
  if (!prefill) chatInput.value = ''

  chatMessages.value.push({ role: 'user', content: question })
  const historyPayload = chatMessages.value.map((m) => ({ role: m.role, content: m.content }))
  const replyIdx = chatMessages.value.push({ role: 'assistant', content: '' }) - 1
  chatLoading.value = true

  const scrollBottom = () => nextTick(() => {
    if (chatListEl.value) chatListEl.value.scrollTop = chatListEl.value.scrollHeight
  })
  scrollBottom()

  try {
    await learnApi.chat(
      {
        url: props.info.url,
        title: props.info.title || null,
        transcript: effectiveTranscript.value || null,
        transcription_id: localTranscriptionId.value || null,
        messages: historyPayload.slice(-20),
      },
      (event, data) => {
        if (event === 'delta') {
          chatMessages.value[replyIdx].content += String(data || '')
          scrollBottom()
        } else if (event === 'need_asr') {
          chatMessages.value.splice(replyIdx - 1, 2)
          needAsr.value = { ...(data || {}), nextAction: 'chat', pendingQuestion: question }
        } else if (event === 'error') {
          chatError.value = String(data || '回答生成失败')
          if (!chatMessages.value[replyIdx].content) chatMessages.value.splice(replyIdx, 1)
        }
      },
      ctrl.signal,
    )
  } catch (e) {
    if (e.name !== 'AbortError') {
      chatError.value = e.message || 'AI 追问失败'
      if (!chatMessages.value[replyIdx]?.content) chatMessages.value.splice(replyIdx, 1)
    }
  } finally {
    if (chatAbort === ctrl) {
      chatLoading.value = false
      loadMembership()
    }
  }
}

async function confirmAndTranscribe() {
  if (!props.info?.url || asrBusy.value) return
  const pendingAction = needAsr.value?.nextAction || 'summary'
  const pendingQ = needAsr.value?.pendingQuestion || ''
  needAsr.value = null
  asrBusy.value = true
  asrMessage.value = '正在建立转写会话并检查音轨…'
  summaryError.value = ''
  mindmapError.value = ''
  chatError.value = ''

  const pollOnce = async (jobId) => {
    try {
      const state = await api.transcription(jobId)
      asrMessage.value = state.message || '语音识别处理中…'
      if (state.status === 'done' && state.result) {
        asrBusy.value = false
        asrMessage.value = ''
        localTranscript.value = state.result.timed_text || state.result.text || ''
        localTranscriptionId.value = state.id
        emit('transcribed', state.result)
        notify('语音转文字已完成，开始生成 AI 学习内容')
        if (pendingAction === 'mindmap') await runMindmap(true)
        else if (pendingAction === 'chat' && pendingQ) await sendChat(pendingQ)
        else await runSummary(true)
        return
      }
      if (state.status === 'error') {
        asrBusy.value = false
        summaryError.value = state.error || '语音转文字失败'
        return
      }
      asrPollTimer = setTimeout(() => pollOnce(jobId), 1500)
    } catch (e) {
      if (e.status === 404 || e.status === 403) {
        asrBusy.value = false
        summaryError.value = e.message || '转写任务已过期'
      } else {
        asrMessage.value = '网络波动，正在恢复查询原任务（不会重复扣费）…'
        asrPollTimer = setTimeout(() => pollOnce(jobId), 3500)
      }
    }
  }

  try {
    await api.transcriptionSession()
    const created = await api.transcribe({ url: props.info.url, allow_asr: true })
    await pollOnce(created.id)
  } catch (e) {
    asrBusy.value = false
    summaryError.value = e.message || '发起语音转文字失败'
  }
}

async function copySummary() {
  if (!currentSummary.value) return
  try {
    await navigator.clipboard.writeText(currentSummary.value)
    notify('AI 总结已复制到剪贴板')
  } catch {
    notify('复制失败，请手动选中复制', 'error')
  }
}

function exportNotes(ext = 'md') {
  const title = props.info?.title || summaryMeta.value?.title || 'AI视频学习笔记'
  const safeName = title.replace(/[\\/:*?"<>|\r\n]+/g, '_').slice(0, 60) || 'study-note'
  const modeLabel = MODES.find((m) => m.id === mode.value)?.label || '通用精读'
  const blocks = []

  if (ext === 'md') {
    blocks.push(`# ${title}`)
    blocks.push('')
    if (props.info?.platform) blocks.push(`- **平台**：${props.info.platform}`)
    if (props.info?.uploader) blocks.push(`- **作者**：${props.info.uploader}`)
    if (props.info?.url) blocks.push(`- **原视频链接**：${props.info.url}`)
    blocks.push(`- **学习视角**：${modeLabel}`)
    blocks.push('')
    if (currentSummary.value) {
      blocks.push(currentSummary.value)
      blocks.push('')
    }
    if (mindmapMd.value) {
      blocks.push('---', '', '## 思维导图大纲', '', mindmapMd.value, '')
    }
    if (chatMessages.value.length) {
      blocks.push('---', '', '## AI 视频追问记录', '')
      for (const m of chatMessages.value) {
        blocks.push(m.role === 'user' ? `### Q：${m.content}` : `${m.content}\n`)
      }
    }
  } else {
    blocks.push(`【标题】${title}`)
    if (props.info?.url) blocks.push(`【链接】${props.info.url}`)
    blocks.push(`【视角】${modeLabel}`, '')
    if (currentSummary.value) blocks.push('【AI 结构化总结】', currentSummary.value, '')
    if (mindmapMd.value) blocks.push('【思维导图大纲】', mindmapMd.value, '')
    if (chatMessages.value.length) {
      blocks.push('【AI 追问记录】')
      for (const m of chatMessages.value) {
        blocks.push(`${m.role === 'user' ? '问' : '答'}：${m.content}`)
      }
    }
  }

  const blob = new Blob([blocks.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  triggerDownload(url, `${safeName}_学习笔记.${ext}`)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
  notify(`已导出 .${ext} 学习笔记`)
}
</script>

<template>
  <section ref="panel-root" class="rounded-2xl border border-indigo-100 bg-gradient-to-b from-indigo-50/40 via-white to-white p-4 shadow-sm sm:p-5" aria-label="AI 视频助学助手">
    <!-- Header Bar -->
    <div class="flex flex-col gap-3 border-b border-slate-100 pb-3.5 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex flex-wrap items-center gap-2">
        <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 via-indigo-500 to-violet-600 text-white shadow-sm">
          <LearnIcon name="sparkles" :size="16" />
        </span>
        <div>
          <div class="flex flex-wrap items-center gap-2">
            <h4 class="text-base font-bold text-slate-900 sm:text-lg">AI 视频精读与助学</h4>
            <span v-if="hasTranscriptReady" class="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
              文稿已就绪 · 秒级生成
            </span>
          </div>
          <p class="text-xs text-slate-500">快速掌握长视频大纲、核心要点、可视化思维导图与细节追问</p>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <span v-if="internalToast" class="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700">{{ internalToast }}</span>
        <RouterLink v-if="!workbenchMode && info?.url" :to="{ path: '/learn', query: { url: info.url } }"
          class="inline-flex h-9 items-center gap-1.5 rounded-xl border border-indigo-200 bg-white px-3 text-xs font-semibold text-indigo-600 shadow-sm transition hover:bg-indigo-50">
          <LearnIcon name="external" :size="13" />
          <span>沉浸分栏工作台</span>
        </RouterLink>
      </div>
    </div>

    <!-- AI Disabled Warning -->
    <div v-if="!aiEnabled" class="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
      <LearnIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
      <span>AI 功能未启用：请在 <code class="rounded bg-amber-100 px-1">backend/.env</code> 中配置 <code class="rounded bg-amber-100 px-1">DEEPSEEK_API_KEY</code>。</span>
    </div>

    <!-- Sub-Navigation Tabs + Export Actions -->
    <div class="mt-3.5 flex flex-wrap items-center justify-between gap-2">
      <div class="inline-flex flex-wrap rounded-xl bg-slate-100/90 p-1">
        <button v-for="t in [['summary', '智能总结', 'sparkles'], ['mindmap', '思维导图', 'mindmap'], ['chat', 'AI 追问', 'chat']]"
          :key="t[0]" type="button"
          class="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition sm:text-sm"
          :class="activeTab === t[0] ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'"
          @click="switchTab(t[0])">
          <LearnIcon :name="t[2]" :size="15" />
          <span>{{ t[1] }}</span>
          <span v-if="t[0] === 'chat' && chatMessages.length" class="rounded-full bg-indigo-100 px-1.5 text-[10px] text-indigo-700">
            {{ Math.ceil(chatMessages.length / 2) }}
          </span>
        </button>
      </div>

      <div v-if="currentSummary || mindmapMd || chatMessages.length" class="flex flex-wrap items-center gap-1.5 text-xs">
        <button v-if="currentSummary" type="button" class="btn-ghost inline-flex h-8 items-center gap-1 px-2.5 font-medium" @click="copySummary">
          <LearnIcon name="copy" :size="13" /> 复制总结
        </button>
        <button type="button" class="btn-ghost inline-flex h-8 items-center gap-1 px-2.5 font-medium" @click="exportNotes('md')">
          <LearnIcon name="download" :size="13" /> 导出 MD
        </button>
        <button type="button" class="btn-ghost inline-flex h-8 items-center gap-1 px-2.5 font-medium" @click="exportNotes('txt')">
          TXT
        </button>
      </div>
    </div>

    <!-- ASR Confirmation Card (Zero Implicit Charge) -->
    <div v-if="needAsr" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50/70 p-4 text-sm text-slate-800">
      <div class="flex items-start gap-2.5">
        <LearnIcon name="alert" :size="18" class="mt-0.5 shrink-0 text-amber-600" />
        <div class="flex-1">
          <p class="font-semibold text-slate-900">{{ needAsr.message || '未提取到可下载的平台字幕' }}</p>
          <p class="mt-1 text-xs leading-5 text-slate-600">
            确认后将提取视频音轨并通过云端语音识别生成带时间轴文稿（最长 {{ asrMaxMinutes }} 分钟，消耗你的每月语音识别额度），识别完成后自动生成 AI 总结；同一视频切换学习视角、生成思维导图或追问均自动复用，不会重复扣费。
          </p>
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" :disabled="needAsr.asr_enabled === false || asrBusy"
              class="btn-primary inline-flex h-10 items-center gap-1.5 rounded-xl px-4 text-xs font-bold sm:text-sm"
              @click="confirmAndTranscribe">
              <LearnIcon name="sparkles" :size="15" /> 确认语音转文字并总结
            </button>
            <button type="button" class="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
              @click="needAsr = null">
              暂不转写
            </button>
          </div>
          <p v-if="needAsr.asr_enabled === false" class="mt-2 text-xs text-rose-600">
            当前服务器尚未配置语音识别密钥（DASHSCOPE_API_KEY），请联系管理员启用。
          </p>
        </div>
      </div>
    </div>

    <!-- ASR Running Progress -->
    <div v-if="asrBusy" class="mt-4 flex items-center gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/80 p-4 text-sm text-indigo-800">
      <LearnIcon name="loader" :size="18" class=" shrink-0 animate-spin" />
      <div>
        <div class="font-semibold">正在进行语音转文字…</div>
        <div class="mt-0.5 text-xs text-indigo-700">{{ asrMessage }}</div>
      </div>
    </div>

    <!-- TAB 1: SUMMARY -->
    <div v-show="activeTab === 'summary'" class="mt-4">
      <!-- Mode Selector + Trigger -->
      <div class="flex flex-col gap-2.5 rounded-xl border border-slate-200/80 bg-slate-50/70 p-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="px-1 text-xs font-semibold text-slate-500">学习视角：</span>
          <button v-for="m in MODES" :key="m.id" type="button" :title="m.desc"
            class="rounded-lg px-2.5 py-1.5 text-xs font-semibold transition"
            :class="mode === m.id ? 'bg-indigo-600 text-white shadow-sm' : 'bg-white text-slate-600 hover:text-indigo-600'"
            @click="selectMode(m.id)">
            {{ m.label }}
          </button>
        </div>

        <button type="button" :disabled="!aiEnabled || !info?.url || summaryLoading || asrBusy"
          class="btn-primary inline-flex h-9 items-center justify-center gap-1.5 rounded-xl px-4 text-xs font-bold sm:text-sm"
          @click="runSummary(true)">
          <LearnIcon :name="summaryLoading ? 'loader' : (currentSummary ? 'refresh' : 'sparkles')" :size="15"
            :class="{ 'animate-spin': summaryLoading }" />
          <span>{{ summaryLoading ? '正在总结…' : (currentSummary ? '重新生成' : '一键 AI 总结') }}</span>
        </button>
      </div>

      <p v-if="summaryError" class="mt-3 flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-xs text-rose-600 sm:text-sm">
        <LearnIcon name="alert" :size="15" class="shrink-0" /> {{ summaryError }}
      </p>

      <!-- Empty Invite State -->
      <div v-if="!currentSummary && !summaryLoading && !needAsr && !asrBusy"
        class="mt-3 rounded-2xl border border-dashed border-slate-200 bg-white/80 px-4 py-8 text-center">
        <p class="text-sm font-semibold text-slate-700">选择上方学习视角，点击「一键 AI 总结」快速提炼全片知识</p>
        <p class="mt-1 text-xs text-slate-400">支持一句话主旨、带时间戳章节大纲、核心术语解释；超长视频自动分段汇总不截断</p>
      </div>

      <!-- Streaming / Rendered Summary -->
      <div v-if="currentSummary || summaryLoading" class="mt-3 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
        <div class="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2.5 text-xs text-slate-500">
          <div class="flex flex-wrap items-center gap-2">
            <span v-if="sourceLabel" class="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-600">{{ sourceLabel }}</span>
            <span v-if="summaryMeta?.segmented" class="rounded-md bg-indigo-50 px-2 py-0.5 font-medium text-indigo-700">长视频全片分段汇总</span>
            <span>点击 <span class="ts-pill pointer-events-none">▶ 00:00</span> 可空降对应片段</span>
          </div>
          <div v-if="summaryLoading" class="inline-flex items-center gap-1.5 font-medium text-indigo-600">
            <LearnIcon name="loader" :size="13" class="animate-spin" />
            <span>{{ summaryStatus || 'AI 正在输出…' }}</span>
          </div>
        </div>

        <div class="learn-prose text-sm" @click="onProseClick" v-html="summaryHtml"></div>
      </div>
    </div>

    <!-- TAB 2: MINDMAP -->
    <div v-show="activeTab === 'mindmap'" class="mt-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p class="text-xs text-slate-500">将整支视频的主旨、章节与关键论点转化为可视化知识树，支持导出 PNG / SVG / Markdown。</p>
        <button type="button" :disabled="!aiEnabled || !info?.url || mindmapLoading || asrBusy"
          class="btn-primary inline-flex h-9 items-center gap-1.5 rounded-xl px-4 text-xs font-bold"
          @click="runMindmap(true)">
          <LearnIcon :name="mindmapLoading ? 'loader' : (mindmapMd ? 'refresh' : 'mindmap')" :size="14"
            :class="{ 'animate-spin': mindmapLoading }" />
          <span>{{ mindmapLoading ? '正在绘制脑图…' : (mindmapMd ? '重新生成脑图' : '生成思维导图') }}</span>
        </button>
      </div>

      <p v-if="mindmapError" class="mb-3 flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-xs text-rose-600">
        <LearnIcon name="alert" :size="15" class="shrink-0" /> {{ mindmapError }}
      </p>

      <div v-if="mindmapLoading && !mindmapMd" class="flex flex-col items-center justify-center rounded-2xl border border-slate-200 bg-white py-14 text-sm text-indigo-600">
        <LearnIcon name="loader" :size="24" class="animate-spin" />
        <p class="mt-2.5 font-medium">正在梳理视频层级脉络并生成交互式思维导图…</p>
      </div>

      <MindMapView v-else-if="mindmapMd" :markdown="mindmapMd" :title="info?.title || summaryMeta?.title || '思维导图'"
        @seek="handleSeek" @notify="notify" />

      <div v-else-if="!needAsr && !asrBusy" class="rounded-2xl border border-dashed border-slate-200 bg-white/80 px-4 py-10 text-center">
        <p class="text-sm font-semibold text-slate-700">点击右上角「生成思维导图」一键可视化全片知识脉络</p>
        <p class="mt-1 text-xs text-slate-400">支持拖拽平移、滚轮缩放、节点折叠，以及导出高清图片与 XMind/Obsidian 大纲</p>
      </div>
    </div>

    <!-- TAB 3: AI CHAT -->
    <div v-show="activeTab === 'chat'" class="mt-4">
      <!-- Suggested Question Chips -->
      <div class="mb-3">
        <div class="mb-1.5 flex items-center justify-between text-xs text-slate-500">
          <span>快捷追问（点击直接提问）：</span>
          <button v-if="chatMessages.length" type="button" class="inline-flex items-center gap-1 text-slate-400 hover:text-rose-600"
            @click="chatMessages = []; chatError = ''">
            <LearnIcon name="trash" :size="12" /> 清空对话
          </button>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <button v-for="q in suggestedQuestions" :key="q" type="button" :disabled="chatLoading || !aiEnabled"
            class="rounded-full border border-indigo-100 bg-indigo-50/70 px-3 py-1.5 text-left text-xs font-medium text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-100 disabled:opacity-50"
            @click="sendChat(q)">
            {{ q }}
          </button>
        </div>
      </div>

      <!-- Conversation List -->
      <div v-if="chatMessages.length" ref="chat-list"
        class="mb-3 max-h-[380px] space-y-3 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3.5 sm:p-4"
        @click="onProseClick">
        <div v-for="(msg, idx) in chatMessages" :key="idx"
          class="flex" :class="msg.role === 'user' ? 'justify-end' : 'justify-start'">
          <div v-if="msg.role === 'user'"
            class="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-3.5 py-2.5 text-xs leading-6 text-white shadow-sm sm:text-sm">
            {{ msg.content }}
          </div>
          <div v-else
            class="max-w-[92%] rounded-2xl rounded-bl-sm border border-slate-100 bg-slate-50/90 px-4 py-3 text-xs text-slate-800 sm:text-sm">
            <div v-if="!msg.content && chatLoading" class="inline-flex items-center gap-1.5 text-xs text-indigo-600">
              <LearnIcon name="loader" :size="14" class="animate-spin" /> 正在结合视频文稿思考…
            </div>
            <div v-else class="learn-prose" v-html="renderLearningMarkdown(msg.content)"></div>
          </div>
        </div>
      </div>

      <p v-if="chatError" class="mb-3 flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">
        <LearnIcon name="alert" :size="14" class="shrink-0" /> {{ chatError }}
      </p>

      <!-- Question Input -->
      <form class="flex gap-2" @submit.prevent="sendChat()">
        <input v-model="chatInput" type="text" maxlength="1000"
          placeholder="针对视频中的概念、细节或结论继续提问…"
          class="input-control flex-1 rounded-xl px-3.5 py-2.5 text-xs sm:text-sm" />
        <button type="submit" :disabled="!chatInput.trim() || chatLoading || !aiEnabled || !info?.url"
          class="btn-primary inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl px-4 text-xs font-bold sm:text-sm">
          <LearnIcon :name="chatLoading ? 'loader' : 'send'" :size="14" :class="{ 'animate-spin': chatLoading }" />
          <span>发送</span>
        </button>
      </form>
    </div>
  </section>
</template>
