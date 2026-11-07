<script setup>
import { computed, onUnmounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import JobProgress from '../components/JobProgress.vue'
import { api, extractUrls, pollJob } from '../api.js'

const MAX = 20
const text = ref('')
const kind = ref('video')
const quality = ref(1080)
const job = ref(null)
const error = ref('')
let stop = null

const urls = computed(() => extractUrls(text.value))
const busy = computed(() => job.value && !['done', 'error'].includes(job.value.status))
const statusStyle = {
  queued: ['clock', 'text-slate-400', '等待中'],
  running: ['loader', 'text-indigo-500 animate-spin', '下载中'],
  processing: ['loader', 'text-violet-500 animate-spin', '处理中'],
  done: ['check', 'text-emerald-500', '完成'],
  error: ['alert', 'text-rose-500', '失败'],
}

async function start() {
  error.value = ''
  if (!urls.value.length) return (error.value = '未识别到有效链接')
  if (urls.value.length > MAX) return (error.value = `单次最多 ${MAX} 条，当前 ${urls.value.length} 条`)
  stop?.()
  try {
    job.value = await api.batch({ urls: urls.value, kind: kind.value, quality: kind.value === 'video' ? quality.value : null })
    stop = pollJob(job.value.id, (j) => (job.value = { ...job.value, ...j }), 1200)
  } catch (e) {
    error.value = e.message
  }
}
onUnmounted(() => stop?.())
</script>

<template>
  <section class="hero-bg min-h-[70vh] py-12 sm:py-16">
    <div class="mx-auto max-w-4xl px-4 sm:px-6">
      <div class="text-center">
        <span class="pro-badge">PRO 功能 · 限时免费</span>
        <h1 class="mt-3 text-3xl font-extrabold tracking-tight sm:text-5xl"><span class="text-grad">批量下载</span>，一键打包 ZIP</h1>
        <p class="mx-auto mt-4 max-w-2xl text-sm text-slate-600 sm:text-base">一次粘贴多条链接（每行一条，或直接粘贴含链接的分享文案），后台自动去重、逐条下载，完成后打包为 ZIP。</p>
      </div>

      <div class="input-shell mt-8 rounded-[1.75rem] p-4 sm:p-6">
        <textarea v-model="text" rows="7" :disabled="busy"
          placeholder="https://www.bilibili.com/video/BV1xxxx&#10;https://www.youtube.com/watch?v=xxxx&#10;【分享文案】https://b23.tv/xxxx 也可以直接粘贴"
          class="input-control w-full resize-y rounded-2xl p-4 font-mono text-sm"></textarea>
        <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
          <div class="text-sm text-slate-500">
            已识别 <b :class="urls.length > MAX ? 'text-rose-600' : 'text-indigo-600'">{{ urls.length }}</b> / {{ MAX }} 条链接（已自动去重）
          </div>
          <div class="flex flex-wrap gap-2">
            <select v-model="kind" class="input-control rounded-xl px-3 py-2 text-sm" :disabled="busy">
              <option value="video">视频 MP4</option>
              <option value="audio">音频 MP3</option>
            </select>
            <select v-if="kind === 'video'" v-model="quality" class="input-control rounded-xl px-3 py-2 text-sm" :disabled="busy">
              <option :value="2160">最高 4K</option>
              <option :value="1080">最高 1080P</option>
              <option :value="720">最高 720P</option>
              <option :value="480">最高 480P（省流量）</option>
            </select>
          </div>
        </div>
        <button class="btn-primary mt-4 flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold" :disabled="busy || !urls.length" @click="start">
          <Icon :name="busy ? 'loader' : 'layers'" :size="18" :class="{ 'animate-spin': busy }" />
          {{ busy ? '批量下载中…' : `开始批量下载（${urls.length} 条）` }}
        </button>
        <p v-if="error" class="mt-3 flex items-center gap-2 text-sm text-rose-600"><Icon name="alert" :size="16" /> {{ error }}</p>

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
    </div>
  </section>
</template>
