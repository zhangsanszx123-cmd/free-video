<script setup>
import { computed, onUnmounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import JobProgress from '../components/JobProgress.vue'
import BatchSubtitleResults from '../components/BatchSubtitleResults.vue'
import { api, extractUrls, pollJob } from '../api.js'

const MAX = 20
const text = ref('')
const kind = ref('subtitle')
const quality = ref(1080)
const job = ref(null)
const error = ref('')
const subtitlePanel = ref(null)
const subtitleBusy = ref(false)
let stop = null
const submitting = ref(false)
let disposed = false

const urls = computed(() => extractUrls(text.value))
const busy = computed(() => submitting.value || subtitleBusy.value || Boolean(job.value && !['done', 'error'].includes(job.value.status)))
const statusStyle = {
  queued: ['clock', 'text-slate-400', '等待中'],
  running: ['loader', 'text-indigo-500 animate-spin', '下载中'],
  processing: ['loader', 'text-violet-500 animate-spin', '处理中'],
  done: ['check', 'text-emerald-500', '完成'],
  error: ['alert', 'text-rose-500', '失败'],
}

async function start() {
  if (busy.value) return
  error.value = ''
  if (!urls.value.length) return (error.value = '未识别到有效链接')
  if (urls.value.length > MAX) return (error.value = `单次最多 ${MAX} 条，当前 ${urls.value.length} 条`)
  if (kind.value === 'subtitle') {
    await subtitlePanel.value?.start(urls.value)
    return
  }
  stop?.()
  submitting.value = true
  try {
    const created = await api.batch({ urls: urls.value, kind: kind.value, quality: kind.value === 'video' ? quality.value : null })
    if (disposed) return
    job.value = created
    stop = pollJob(job.value.id, (j) => (job.value = { ...job.value, ...j }), 1200)
  } catch (e) {
    if (!disposed) error.value = e.message
  } finally {
    submitting.value = false
  }
}
onUnmounted(() => { disposed = true; stop?.() })
</script>

<template>
  <section class="hero-bg min-h-[70vh] py-12 sm:py-16">
    <div class="mx-auto max-w-6xl px-4 sm:px-6">
      <div class="text-center">
        <span class="pro-badge">PRO 功能 · 限时免费</span>
        <h1 class="mt-3 text-3xl font-extrabold tracking-tight sm:text-5xl"><span class="text-grad">批量提取</span>，素材与字幕一站整理</h1>
        <p class="mx-auto mt-4 max-w-2xl text-sm leading-7 text-slate-600 sm:text-base">一次粘贴多条视频链接，自动提取视频、音频或字幕。字幕结果逐条可见，确认内容后再打包下载。</p>
        <ol class="mx-auto mt-6 flex max-w-lg items-center justify-center gap-3 text-xs font-medium text-slate-500 sm:gap-6"><li v-for="(step, i) in ['粘贴链接', '自动提取', '查看与导出']" :key="step" class="inline-flex items-center gap-2"><span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-700">{{ i + 1 }}</span>{{ step }}</li></ol>
      </div>

      <div class="input-shell mx-auto mt-8 max-w-4xl rounded-[1.75rem] p-4 sm:p-6">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3"><h2 class="font-bold text-slate-900">批量提取工作台</h2><span class="text-xs text-slate-500">最多 {{ MAX }} 条 · 自动去重</span></div>
        <textarea aria-label="批量视频链接或分享文案" v-model="text" rows="7" :disabled="busy"
          placeholder="https://www.bilibili.com/video/BV1xxxx&#10;https://www.youtube.com/watch?v=xxxx&#10;【分享文案】https://b23.tv/xxxx 也可以直接粘贴"
          class="input-control w-full resize-y rounded-2xl p-4 font-mono text-sm"></textarea>
        <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
          <div class="text-sm text-slate-500">
            已识别 <b :class="urls.length > MAX ? 'text-rose-600' : 'text-indigo-600'">{{ urls.length }}</b> / {{ MAX }} 条链接（已自动去重）
          </div>
          <div class="flex flex-wrap gap-2">
            <select aria-label="下载格式" v-model="kind" class="input-control rounded-xl px-3 py-2 text-sm" :disabled="busy">
              <option value="subtitle">字幕 SRT · 支持语音识别</option>
              <option value="video">视频 MP4</option>
              <option value="audio">音频 MP3</option>
            </select>
            <select aria-label="视频清晰度" v-if="kind === 'video'" v-model="quality" class="input-control rounded-xl px-3 py-2 text-sm" :disabled="busy">
              <option :value="2160">最高 4K</option>
              <option :value="1080">最高 1080P</option>
              <option :value="720">最高 720P</option>
              <option :value="480">最高 480P（省流量）</option>
            </select>
          </div>
        </div>
        <p v-if="kind === 'subtitle'" class="mt-4 flex items-start gap-2 rounded-xl border border-amber-100 bg-amber-50/80 p-3 text-xs leading-6 text-amber-800"><Icon name="alert" :size="16" class="mt-1 shrink-0" /><span>优先提取平台字幕；无字幕时自动调用付费语音识别，消耗管理员配置的 API 预算。单条最长 60 分钟，以服务器配置为准；网络或鉴权失败不会自动转为收费识别。</span></p>
        <button class="btn-primary mt-4 flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold" :disabled="busy || !urls.length" @click="start">
          <Icon :name="busy ? 'loader' : 'layers'" :size="18" :class="{ 'animate-spin': busy }" />
          {{ busy ? (kind === 'subtitle' ? '正在提取字幕…' : '批量下载中…') : kind === 'subtitle' ? `开始批量提取字幕（${urls.length} 条）` : `开始批量下载（${urls.length} 条）` }}
        </button>
        <p role="alert" v-if="error" class="mt-3 flex items-center gap-2 text-sm text-rose-600"><Icon name="alert" :size="16" /> {{ error }}</p>

        <JobProgress v-if="job" :job="job" class="mt-4">
          <ul v-if="job.items?.length" class="mt-4 divide-y divide-slate-100 rounded-xl border border-slate-100">
            <li v-for="(it, i) in job.items" :key="i" class="flex items-center gap-3 px-3 py-2.5 text-sm">
              <Icon :name="statusStyle[it.status][0]" :size="16" :class="statusStyle[it.status][1]" class="shrink-0" />
              <div class="min-w-0 flex-1">
                <div class="truncate font-medium text-slate-800">{{ it.title || it.url }}</div>
                <div v-if="it.error" class="truncate text-xs text-rose-500">{{ it.error }}</div>
              </div>
              <span class="shrink-0 text-xs text-slate-500">{{ it.status === 'running' ? Math.round(it.progress) + '%' : statusStyle[it.status][2] }}</span>
            </li>
          </ul>
        </JobProgress>
      </div>
      <BatchSubtitleResults ref="subtitlePanel" v-show="kind === 'subtitle'" @busy="subtitleBusy = $event" @restored="kind = 'subtitle'" />
    </div>
  </section>
</template>
