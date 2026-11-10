<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from './Icon.vue'
import { api, downloadArchive, triggerDownload } from '../api.js'

const emit = defineEmits(['busy', 'restored'])
const job = ref(null)
const submitting = ref(false)
const error = ref('')
const reconnecting = ref(false)
const selected = ref(0)
const selectionPinned = ref(false)
const timed = ref(true)
const notice = ref('')
const exporting = ref(false)
const busy = computed(() => submitting.value || Boolean(job.value && !['done', 'error'].includes(job.value.status)))
const active = computed(() => job.value?.items?.[selected.value])
const preview = computed(() => timed.value ? active.value?.result?.timed_text : active.value?.result?.text)
const canExport = computed(() => job.value && !busy.value && job.value.succeeded > 0)
const progress = computed(() => job.value?.total ? Math.round(job.value.completed / job.value.total * 100) : 0)
const stages = { queued: '等待处理', subtitles: '检查平台字幕', audio: '获取视频音轨', upload: '上传音轨', recognizing: '云端语音识别', export: '生成字幕', done: '提取完成', error: '提取失败' }
const sources = { platform_subtitle: '平台字幕', automatic_subtitle: '平台自动字幕', asr: '语音识别' }
let timer
let toastTimer
let controller = new AbortController()
let disposed = false
const storageKey = 'fv-batch-subtitles'
watch(busy, (value) => emit('busy', value), { immediate: true })

function remember(id) {
  try { id ? localStorage.setItem(storageKey, id) : localStorage.removeItem(storageKey) } catch { /* storage is optional */ }
}
function notify(message) {
  notice.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { notice.value = '' }, 3000)
}
async function poll(id) {
  if (disposed) return
  try {
    const next = await api.batchTranscription(id, controller.signal)
    if (disposed) return
    job.value = next
    reconnecting.value = false
    error.value = ''
    if (!selectionPinned.value && !active.value?.result) {
      const first = next.items.findIndex((item) => item.status === 'done')
      if (first >= 0 && !next.items[selected.value]?.result) selected.value = first
    }
    if (['done', 'error'].includes(next.status)) return
  } catch (e) {
    if (disposed || e.name === 'AbortError') return
    error.value = e.message
    if ([403, 404].includes(e.status)) { remember(null); job.value = null; return }
    reconnecting.value = true
  }
  timer = setTimeout(() => poll(id), reconnecting.value ? 4000 : 1200)
}
async function start(urls) {
  if (busy.value) return
  submitting.value = true
  error.value = ''
  clearTimeout(timer)
  try {
    await api.transcriptionSession()
    if (disposed) return
    const created = await api.batchTranscribe(urls, controller.signal)
    if (disposed) return
    job.value = created
    selected.value = 0
    selectionPinned.value = false
    remember(created.id)
    poll(created.id)
  } catch (e) {
    if (!disposed && e.name !== 'AbortError') error.value = e.message
  } finally { submitting.value = false }
}
async function copy(all = false) {
  const text = all
    ? job.value.items.filter(i => i.result).map(i => `【${i.title}】\n${i.result.text}`).join('\n\n')
    : preview.value
  try { await navigator.clipboard.writeText(text || ''); notify('已复制到剪贴板') }
  catch { notify('复制失败，请手动选择正文复制') }
}
function downloadSingle() {
  if (!active.value?.result?.srt) return
  const name = (active.value.title || '字幕').replace(/[\\/:*?"<>|\r\n]/g, '_').slice(0, 80)
  const url = URL.createObjectURL(new Blob([active.value.result.srt], { type: 'application/x-subrip;charset=utf-8' }))
  triggerDownload(url, `${name}.srt`)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}
async function downloadZip() {
  if (!canExport.value || exporting.value) return
  exporting.value = true
  try {
    await downloadArchive(`/api/batch-transcriptions/${job.value.id}/file`, 'FreeVideo-subtitles.zip', controller.signal)
  } catch (e) { if (!disposed) notify(e.message) }
  finally { exporting.value = false }
}
onMounted(() => {
  let id
  try { id = localStorage.getItem(storageKey) } catch { /* ignore */ }
  if (id && /^[a-f0-9]{32}$/.test(id)) {
    emit('restored')
    job.value = { id, status: 'running', total: 0, completed: 0, items: [] }
    poll(id)
  }
})
onUnmounted(() => { disposed = true; controller.abort(); clearTimeout(timer); clearTimeout(toastTimer) })
defineExpose({ start, busy })
</script>

<template>
  <section aria-label="字幕提取过程与结果" class="mt-6 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl shadow-indigo-950/5">
    <div v-if="!job" class="px-5 py-14 text-center sm:py-16">
      <span class="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-200"><Icon name="captions" :size="27" /></span>
      <h2 class="mt-5 text-lg font-bold text-slate-900">开始提取后，这里会逐条展示字幕结果</h2>
      <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">优先读取平台字幕，无字幕时自动使用付费语音识别。<br class="hidden sm:block" />查看完整内容后，再一键打包下载。</p>
      <div class="mt-6 flex flex-wrap justify-center gap-2 text-xs font-medium text-indigo-700">
        <span v-for="label in ['自动去重', '过程实时可见', '字幕预览与导出']" :key="label" class="rounded-lg bg-indigo-50 px-3 py-2">{{ label }}</span>
      </div>
    </div>
    <template v-else>
      <header class="border-b border-slate-100 px-5 py-5 sm:px-6">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div><h2 class="text-lg font-bold text-slate-900">{{ busy ? '正在提取字幕' : '字幕提取结果' }}</h2><p class="mt-1 text-xs text-slate-500">结果在本批次结束后保留 {{ Math.round((job.ttl_seconds || 1800) / 60) }} 分钟 · 同一浏览器可返回继续查看</p></div>
          <div role="status" class="flex flex-wrap gap-2 text-xs font-semibold">
            <span class="rounded-lg bg-indigo-50 px-3 py-2 text-indigo-700">已处理 {{ job.completed }} / {{ job.total }}</span>
            <span class="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-700">成功 {{ job.succeeded || 0 }}</span>
            <span v-if="job.failed" class="rounded-lg bg-rose-50 px-3 py-2 text-rose-700">失败 {{ job.failed }}</span>
          </div>
        </div>
        <div role="progressbar" aria-label="已处理链接比例" :aria-valuenow="progress || 0" aria-valuemin="0" aria-valuemax="100" class="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100"><div class="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all" :style="{ width: `${progress || 0}%` }"></div></div>
      </header>
      <div class="grid lg:grid-cols-[minmax(260px,0.8fr)_minmax(0,1.4fr)]">
        <div class="max-h-72 overflow-y-auto border-b border-slate-100 bg-slate-50/60 p-3 lg:max-h-[480px] lg:border-b-0 lg:border-r">
          <button v-for="(item, index) in job.items" :key="item.url" type="button" :aria-pressed="selected === index" class="mb-2 flex w-full gap-3 rounded-2xl border p-3 text-left transition last:mb-0" :class="selected === index ? 'border-indigo-200 bg-white shadow-sm' : 'border-transparent hover:bg-white'" @click="selected = index; selectionPinned = true">
            <span class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl" :class="item.status === 'done' ? 'bg-emerald-50 text-emerald-600' : item.status === 'error' ? 'bg-rose-50 text-rose-600' : 'bg-indigo-50 text-indigo-600'"><Icon :name="item.status === 'done' ? 'check' : item.status === 'error' ? 'alert' : item.status === 'queued' ? 'clock' : 'loader'" :size="16" :class="{ 'animate-spin': ['running', 'processing'].includes(item.status) }" /></span>
            <span class="min-w-0 flex-1"><span class="block truncate text-sm font-semibold text-slate-800">{{ index + 1 }}. {{ item.title || '等待读取视频信息' }}</span><span class="mt-1 block truncate text-[11px] text-slate-400">{{ item.url }}</span><span class="mt-1.5 block text-xs leading-5" :class="item.status === 'error' ? 'text-rose-600' : 'text-slate-500'">{{ item.error || (item.status === 'done' ? sources[item.result?.source] || '提取完成' : item.message || stages[item.stage]) }}</span></span>
          </button>
        </div>
        <div class="min-w-0 p-5 sm:p-6">
          <template v-if="active?.result">
            <div class="flex flex-wrap items-start justify-between gap-3"><div class="min-w-0"><h3 class="break-words font-bold text-slate-900">{{ active.title }}</h3><p class="mt-1 text-xs text-slate-500">{{ sources[active.result.source] || '字幕' }} · {{ active.result.cues }} 条字幕</p></div><label class="inline-flex min-h-11 items-center gap-2 text-xs text-slate-600"><input v-model="timed" type="checkbox" class="accent-indigo-600" /> 显示时间戳</label></div>
            <pre class="mt-4 max-h-72 min-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-2xl bg-slate-50 p-4 font-sans text-sm leading-7 text-slate-700 sm:max-h-80">{{ preview }}</pre>
            <div class="mt-4 flex flex-wrap gap-2"><button type="button" class="btn-ghost min-h-11 px-4 text-sm font-semibold" @click="copy()">复制当前字幕</button><button type="button" class="btn-ghost min-h-11 px-4 text-sm font-semibold" @click="downloadSingle">下载 SRT</button></div>
          </template>
          <div v-else class="flex min-h-64 flex-col items-center justify-center text-center"><Icon :name="active?.status === 'error' ? 'alert' : 'captions'" :size="32" class="text-indigo-300" /><h3 class="mt-4 font-semibold text-slate-700">{{ active?.status === 'error' ? '这条视频未能完成提取' : '字幕完成后即可在这里预览' }}</h3><p class="mt-2 max-w-sm break-words text-sm leading-6 text-slate-500">{{ active?.error || '左侧可查看每条链接的处理阶段，已完成的字幕可以立即展开。' }}</p></div>
        </div>
      </div>
      <footer class="flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 bg-slate-50/50 px-5 py-5 sm:px-6"><p class="text-xs leading-6 text-slate-500">{{ busy ? '后台处理中，可先查看已完成的字幕。' : job.succeeded ? '提取已结束，打包仅包含成功结果。' : '本批次没有成功结果，请查看每条失败原因。' }}<br />预览、复制和下载不会再次调用识别。</p><div class="flex w-full flex-wrap gap-2 sm:w-auto"><button type="button" :disabled="!job.succeeded" class="btn-ghost min-h-11 flex-1 px-4 text-sm font-semibold disabled:opacity-40 sm:flex-none" @click="copy(true)">复制全部正文</button><button type="button" :disabled="!canExport || exporting" class="btn-primary inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl px-5 text-sm font-bold sm:flex-none" @click="downloadZip"><Icon name="download" :size="16" />{{ exporting ? '正在准备下载…' : '打包下载字幕' }}</button></div></footer>
    </template>
    <p v-if="error" role="alert" class="mx-5 mb-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-600">{{ reconnecting ? '连接中断，正在恢复同一任务的进度，不会重新发起识别。' : error }}</p>
    <p v-if="notice" role="status" class="mx-5 mb-5 rounded-xl bg-indigo-50 p-3 text-sm text-indigo-700">{{ notice }}</p>
  </section>
</template>
