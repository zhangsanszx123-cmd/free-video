<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import Icon from './Icon.vue'
import JobProgress from './JobProgress.vue'
import { api, fmt, pollJob } from '../api.js'

const props = defineProps({ info: { type: Object, required: true }, mode: { type: String, default: 'video' } })

const quality = ref(null)
const subLang = ref('')
const job = ref(null)
const error = ref('')
let stop = null

const qualities = computed(() => props.info.qualities || [])
watch(() => props.info, (info) => {
  quality.value = (info.qualities || []).find((q) => q.height <= 1080)?.height ?? info.qualities?.[0]?.height ?? null
  subLang.value = info.subtitles?.[0]?.lang || ''
  job.value = null
  error.value = ''
}, { immediate: true })

const thumb = computed(() => props.info.thumbnail?.replace(/^http:\/\//, 'https://'))

async function start(kind) {
  error.value = ''
  stop?.()
  try {
    const body = kind === 'subtitle'
      ? { url: props.info.url, lang: subLang.value || null }
      : { url: props.info.url, quality: quality.value, kind }
    const created = await (kind === 'subtitle' ? api.subtitles(body) : api.download(body))
    job.value = created
    stop = pollJob(created.id, (j) => (job.value = { ...job.value, ...j }))
  } catch (e) {
    error.value = e.message
  }
}

function directDownload() {
  // cross-origin links ignore the download attribute; open in a new tab (long-press / "save video" on phones)
  window.open(props.info.direct.url, '_blank', 'noopener')
}
onUnmounted(() => stop?.())
</script>

<template>
  <div class="glass-card overflow-hidden rounded-3xl text-left">
    <div class="flex flex-col gap-4 p-4 sm:flex-row sm:p-5">
      <div class="relative aspect-video w-full shrink-0 overflow-hidden rounded-2xl bg-slate-200 sm:w-64">
        <img v-if="thumb" :src="thumb" referrerpolicy="no-referrer" alt="" class="h-full w-full object-cover" />
        <span v-if="info.duration" class="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs font-medium text-white">
          {{ fmt.duration(info.duration) }}
        </span>
        <span class="absolute left-2 top-2 rounded-md bg-white/90 px-2 py-0.5 text-xs font-semibold text-indigo-700">{{ info.platform }}</span>
      </div>
      <div class="min-w-0 flex-1">
        <h3 class="line-clamp-2 text-base font-bold leading-snug text-slate-950 sm:text-lg">{{ info.title }}</h3>
        <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
          <span v-if="info.uploader">UP / 作者：{{ info.uploader }}</span>
          <span v-if="info.view_count">播放 {{ fmt.count(info.view_count) }}</span>
          <span v-if="qualities.length">{{ qualities.length }} 种清晰度</span>
          <span v-if="info.subtitles?.length">{{ info.subtitles.length }} 条字幕</span>
        </div>

        <template v-if="mode === 'video'">
          <div class="mt-4 text-xs font-semibold text-slate-500">选择清晰度</div>
          <div class="mt-2 flex flex-wrap gap-2">
            <button v-for="q in qualities" :key="q.height"
              class="relative rounded-xl border px-3 py-2 text-sm font-semibold transition"
              :class="quality === q.height ? 'border-indigo-500 bg-indigo-50 text-indigo-700 ring-2 ring-indigo-500/15' : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-300'"
              @click="quality = q.height">
              {{ q.label }}
              <span v-if="q.size" class="ml-1 text-xs font-normal text-slate-400">{{ fmt.size(q.size) }}</span>
              <span v-if="q.pro" class="pro-badge absolute -right-2 -top-2">PRO</span>
            </button>
            <span v-if="!qualities.length" class="rounded-xl border border-indigo-500 bg-indigo-50 px-3 py-2 text-sm font-semibold text-indigo-700">原画 · 最佳画质</span>
          </div>
        </template>
        <template v-else-if="mode === 'subtitle'">
          <div class="mt-4 text-xs font-semibold text-slate-500">选择字幕语言</div>
          <select v-if="info.subtitles?.length" v-model="subLang" class="input-control mt-2 w-full rounded-xl px-3 py-2.5 text-sm sm:w-72">
            <option v-for="s in info.subtitles" :key="s.lang" :value="s.lang">{{ s.name }}（{{ s.lang }}）</option>
          </select>
          <p v-else class="mt-2 text-sm text-amber-600">该视频没有可下载的字幕</p>
        </template>
        <p v-else class="mt-4 text-sm text-slate-600">将提取最佳音质并转码为 <b>MP3 (192kbps)</b>，适合听歌、播客、课程音频。</p>
      </div>
    </div>

    <div class="border-t border-slate-100 bg-slate-50/60 p-4 sm:p-5">
      <div class="flex flex-col gap-2 sm:flex-row">
        <button v-if="mode === 'video'" class="btn-primary flex flex-1 items-center justify-center gap-2 rounded-xl py-3 font-bold"
          :disabled="job && !['done', 'error'].includes(job.status)" @click="start('video')">
          <Icon name="download" :size="18" /> 下载 MP4 {{ qualities.find((q) => q.height === quality)?.label || '' }}
        </button>
        <button v-else-if="mode === 'audio'" class="btn-primary flex flex-1 items-center justify-center gap-2 rounded-xl py-3 font-bold"
          :disabled="job && !['done', 'error'].includes(job.status)" @click="start('audio')">
          <Icon name="music" :size="18" /> 提取 MP3 音频
        </button>
        <button v-else class="btn-primary flex flex-1 items-center justify-center gap-2 rounded-xl py-3 font-bold"
          :disabled="!info.subtitles?.length || (job && !['done', 'error'].includes(job.status))" @click="start('subtitle')">
          <Icon name="captions" :size="18" /> 下载 SRT 字幕
        </button>
        <button v-if="mode === 'video' && info.direct" class="btn-ghost flex items-center justify-center gap-2 px-4 py-3 text-sm font-semibold"
          title="浏览器直连平台下载，不经过服务器" @click="directDownload">
          <Icon name="zap" :size="16" class="text-amber-500" /> 直链秒下 {{ info.direct.height ? info.direct.height + 'P' : '' }}
        </button>
        <RouterLink :to="{ path: '/ai', query: { url: info.url } }" class="btn-ghost flex items-center justify-center gap-2 px-4 py-3 text-sm font-semibold">
          <Icon name="sparkles" :size="16" class="text-violet-500" /> AI 总结 <span class="pro-badge">PRO</span>
        </RouterLink>
      </div>
      <p v-if="error" class="mt-3 flex items-center gap-2 text-sm text-rose-600"><Icon name="alert" :size="16" /> {{ error }}</p>
      <JobProgress v-if="job" :job="job" class="mt-3" />
    </div>
  </div>
</template>
