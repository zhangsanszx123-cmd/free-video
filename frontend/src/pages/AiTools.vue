<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import Icon from '../components/Icon.vue'
import JobProgress from '../components/JobProgress.vue'
import { api, pollJob, streamSSE } from '../api.js'

const route = useRoute()
const tab = ref('summary')
const url = ref(route.query.url || '')
const targetLang = ref('简体中文')
const aiEnabled = ref(true)
const loading = ref(false)
const status = ref('')
const error = ref('')
const meta = ref(null)
const markdown = ref('')
const job = ref(null)
let stop = null
let summaryCtrl = null
const submitting = ref(false)
let disposed = false

const html = computed(() => DOMPurify.sanitize(marked.parse(markdown.value || '')))

onMounted(async () => {
  try {
    aiEnabled.value = (await api.health()).ai_enabled
  } catch { /* ignore */ }
})
onUnmounted(() => { disposed = true; stop?.(); summaryCtrl?.abort() })

async function summarize() {
  if (busy.value) return
  loading.value = true
  error.value = ''
  markdown.value = ''
  meta.value = null
  const ctrl = summaryCtrl = new AbortController()
  try {
    await streamSSE('/api/ai/summary', { url: url.value.trim() }, (event, data) => {
      if (disposed) return
      if (event === 'status') status.value = data
      else if (event === 'meta') meta.value = data
      else if (event === 'delta') markdown.value += data
      else if (event === 'error') error.value = data
    }, ctrl.signal)
  } catch (e) {
    if (!disposed && e.name !== 'AbortError') error.value = e.message
  } finally {
    if (summaryCtrl === ctrl) summaryCtrl = null
    if (!disposed) {
      loading.value = false
      status.value = ''
    }
  }
}

async function translate() {
  if (busy.value) return
  submitting.value = true
  error.value = ''
  stop?.()
  try {
    const created = await api.translate({ url: url.value.trim(), target_lang: targetLang.value })
    if (disposed) return
    job.value = created
    stop = pollJob(job.value.id, (j) => (job.value = { ...job.value, ...j }), 1200)
  } catch (e) {
    if (!disposed) error.value = e.message
  } finally {
    submitting.value = false
  }
}

const busy = computed(() => submitting.value || loading.value || (job.value && !['done', 'error'].includes(job.value.status)))
const run = () => url.value.trim() && !busy.value && (tab.value === 'summary' ? summarize() : translate())
async function copy() {
  try {
    await navigator.clipboard.writeText(markdown.value)
    status.value = '已复制'
  } catch {
    status.value = '复制失败，请手动选择文本复制'
  }
  setTimeout(() => (status.value = ''), 1500)
}
</script>

<template>
  <section class="hero-bg min-h-[70vh] py-12 sm:py-16">
    <div class="mx-auto max-w-4xl px-4 sm:px-6">
      <div class="text-center">
        <span class="rounded-full bg-indigo-50 px-3 py-1 text-xs font-bold text-indigo-700 ring-1 ring-indigo-100">登录后使用</span>
        <h1 class="mt-3 text-3xl font-extrabold tracking-tight sm:text-5xl"><span class="text-grad">AI 视频总结</span> & 双语字幕</h1>
        <p class="mx-auto mt-4 max-w-2xl text-sm text-slate-600 sm:text-base">基于视频字幕 + DeepSeek 大模型：1 小时视频 30 秒读完，外语字幕一键生成中外双语 SRT。</p>
      </div>

      <div v-if="!aiEnabled" class="mt-6 flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        <Icon name="alert" :size="18" class="mt-0.5 shrink-0" />
        AI 功能未启用：管理员需在 <code class="rounded bg-amber-100 px-1">backend/.env</code> 中配置 <code class="rounded bg-amber-100 px-1">DEEPSEEK_API_KEY</code> 后重启服务。
      </div>

      <div class="input-shell mt-6 rounded-[1.75rem] p-4 sm:p-6">
        <div class="inline-flex rounded-xl bg-slate-100/90 p-1" role="tablist" aria-label="AI 工具">
          <button v-for="t in [['summary', 'AI 视频总结', 'sparkles'], ['translate', '字幕翻译', 'translate']]" :key="t[0]"
            type="button" role="tab" :aria-selected="tab === t[0]" class="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold transition"
            :class="tab === t[0] ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500'" @click="tab = t[0]">
            <Icon :name="t[2]" :size="15" /> {{ t[1] }}
          </button>
        </div>
        <form class="mt-3 flex flex-col gap-2 sm:flex-row" @submit.prevent="run">
          <input aria-label="视频链接" :disabled="busy" v-model="url" type="text" inputmode="url" placeholder="粘贴带字幕的视频链接（YouTube、B站等）"
            class="input-control flex-1 rounded-2xl px-4 py-4 text-sm sm:text-base" />
          <select aria-label="翻译目标语言" :disabled="busy" v-if="tab === 'translate'" v-model="targetLang" class="input-control rounded-2xl px-3 py-3 text-sm">
            <option>简体中文</option><option>English</option><option>日本語</option><option>한국어</option>
          </select>
          <button type="submit" :disabled="busy || !url.trim() || !aiEnabled"
            class="btn-primary inline-flex min-h-[54px] items-center justify-center gap-2 rounded-2xl px-7 font-bold">
            <Icon :name="busy ? 'loader' : 'sparkles'" :size="18" :class="{ 'animate-spin': busy }" />
            {{ tab === 'summary' ? (loading ? '总结中…' : '开始总结') : '生成双语字幕' }}
          </button>
        </form>
        <p class="mt-2 text-xs text-slate-400">提示：仅支持有字幕（含自动字幕）的视频；YouTube 大多数视频都有自动字幕。</p>
        <p role="alert" v-if="error" class="mt-3 flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600"><Icon name="alert" :size="16" /> {{ error }}</p>

        <template v-if="tab === 'summary' && (markdown || status || meta)">
          <div class="mt-5 rounded-2xl border border-slate-200 bg-white p-5">
            <div class="flex items-center justify-between gap-3 border-b border-slate-100 pb-3">
              <div class="min-w-0">
                <div class="truncate font-bold text-slate-900">{{ meta?.title || 'AI 总结' }}</div>
                <div class="text-xs text-slate-400">{{ meta ? `基于 ${meta.cues} 条字幕生成` : '' }}</div>
              </div>
              <div class="flex shrink-0 items-center gap-2 text-xs text-indigo-600">
                <Icon v-if="loading" name="loader" :size="14" class="animate-spin" /> {{ status }}
                <button v-if="markdown && !loading" class="btn-ghost px-3 py-1.5" @click="copy">复制</button>
              </div>
            </div>
            <div class="prose-ai mt-2 text-sm text-slate-700" v-html="html"></div>
          </div>
        </template>
        <JobProgress v-if="tab === 'translate' && job" :job="job" class="mt-5" />
      </div>
    </div>
  </section>
</template>
