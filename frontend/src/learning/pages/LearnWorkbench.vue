<script setup>
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import '../learning.css'
import LearnIcon from '../LearnIcon.vue'
import LearnTranscript from '../LearnTranscript.vue'
import AiLearningPanel from '../AiLearningPanel.vue'
import { extractBilibiliBvid, extractYoutubeId, formatTs, platformTimeUrl } from '../learnApi.js'
import { fmt } from '../../api.js'
import { useParseRequest } from '../../useParseRequest.js'

const route = useRoute()
const router = useRouter()

const videoEl = useTemplateRef('native-video')
const audioEl = useTemplateRef('native-audio')

const inputUrl = ref('')
const { loading: parsing, parse: requestParse, cancel: cancelParse } = useParseRequest()
const parseError = ref('')
const info = ref(null)
const transcriptResult = ref(null)
const syncedResult = ref(null)
const embedSeekSec = ref(0)
const embedAutoplay = ref(false)
const toast = ref('')
let toastTimer = null

function showToast(msg) {
  clearTimeout(toastTimer)
  toast.value = msg
  toastTimer = setTimeout(() => { toast.value = '' }, 2500)
}

const thumbUrl = computed(() => info.value?.thumbnail?.replace(/^http:\/\//, 'https://') || '')
const bvid = computed(() => extractBilibiliBvid(info.value?.url || inputUrl.value))
const youtubeId = computed(() => extractYoutubeId(info.value?.url || inputUrl.value))

const bilibiliIframeSrc = computed(() => {
  if (!bvid.value) return ''
  const auto = embedAutoplay.value ? 1 : 0
  return `https://player.bilibili.com/player.html?bvid=${encodeURIComponent(bvid.value)}&high_quality=1&danmaku=0&autoplay=${auto}&t=${embedSeekSec.value}`
})

const youtubeIframeSrc = computed(() => {
  if (!youtubeId.value) return ''
  const auto = embedAutoplay.value ? 1 : 0
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(youtubeId.value)}?start=${embedSeekSec.value}&autoplay=${auto}`
})

const transcriptTimedText = computed(() => transcriptResult.value?.timed_text || '')

async function pasteClipboard() {
  try {
    inputUrl.value = await navigator.clipboard.readText()
  } catch {
    parseError.value = '浏览器限制自动读取剪贴板，请手动粘贴视频链接'
  }
}

async function startParse() {
  const raw = inputUrl.value.trim()
  if (!raw || parsing.value) return
  parseError.value = ''
  info.value = null
  transcriptResult.value = null
  syncedResult.value = null
  embedSeekSec.value = 0
  embedAutoplay.value = false

  try {
    const parsed = await requestParse(raw)
    if (!parsed) return
    info.value = parsed
    router.replace({ path: '/learn', query: { url: parsed.url || raw } }).catch(() => {})
  } catch (e) {
    // Fallback minimal info so subtitle/summary flow can still attempt extraction if parse had transient issue
    if (/^https?:\/\//i.test(raw)) {
      parseError.value = e.message
    } else {
      parseError.value = e.message || '链接解析失败，请检查分享链接是否有效'
    }
  }
}

function handleSeek(seconds) {
  const sec = Math.max(0, Math.floor(Number(seconds) || 0))
  if (info.value?.direct?.url && videoEl.value) {
    videoEl.value.currentTime = sec
    videoEl.value.play?.().catch(() => {})
    showToast(`已定位至 ${formatTs(sec)}`)
    return
  }
  if (bvid.value || youtubeId.value) {
    embedSeekSec.value = sec
    embedAutoplay.value = true
    showToast(`播放器已跳转至 ${formatTs(sec)}`)
    return
  }
  if (info.value?.audio_url && audioEl.value) {
    audioEl.value.currentTime = sec
    audioEl.value.play?.().catch(() => {})
    showToast(`音频已定位至 ${formatTs(sec)}`)
    return
  }
  if (info.value?.url) {
    window.open(platformTimeUrl(info.value.url, sec), '_blank', 'noopener')
    showToast(`已打开原视频 ${formatTs(sec)} 位置`)
  }
}

function onPanelTranscribed(res) {
  transcriptResult.value = res
  syncedResult.value = res
}

onMounted(() => {
  if (route.query.url) {
    inputUrl.value = String(route.query.url)
    startParse()
  }
})
function clearInput() {
  cancelParse()
  inputUrl.value = ''
  info.value = null
  transcriptResult.value = null
  syncedResult.value = null
  parseError.value = ''
  router.replace({ path: '/learn' }).catch(() => {})
}
watch(inputUrl, () => { cancelParse(); parseError.value = '' }, { flush: 'sync' })
onUnmounted(() => clearTimeout(toastTimer))
</script>

<template>
  <section class="hero-bg min-h-[82vh] py-8 sm:py-12">
    <div class="mx-auto max-w-7xl px-4 sm:px-6">
      <!-- Toast -->
      <div v-if="toast" class="fixed left-1/2 top-20 z-50 -translate-x-1/2 rounded-full bg-slate-900/90 px-4 py-2 text-xs font-medium text-white shadow-lg backdrop-blur">
        {{ toast }}
      </div>

      <!-- Compact Header + URL Input -->
      <div class="mx-auto max-w-4xl text-center">
        <span class="rounded-full bg-indigo-50 px-3 py-1 text-xs font-bold text-indigo-700 ring-1 ring-indigo-100">AI 学习工作台 · 登录后使用</span>
        <h1 class="mt-2.5 text-2xl font-extrabold tracking-tight text-slate-950 sm:text-4xl">
          长视频 <span class="text-grad">AI 精读 · 思维导图 · 深度追问</span>
        </h1>
        <p class="mt-2 text-xs text-slate-600 sm:text-sm">
          粘贴 B站、YouTube、抖音等视频链接，一键浓缩长课大纲与核心知识要点，点击时间戳即刻空降原片复盘。
        </p>
      </div>

      <div class="input-shell mx-auto mt-6 max-w-4xl rounded-[1.5rem] p-3 sm:p-4">
        <form class="flex flex-col gap-2 sm:flex-row" @submit.prevent="startParse">
          <div class="relative flex-1">
            <LearnIcon name="link" :size="17" class="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input aria-label="视频链接或分享口令" v-model="inputUrl" type="text" inputmode="url" autocomplete="off"
              placeholder="粘贴视频链接或分享口令（如 https://www.bilibili.com/video/BV... 或抖音分享链接）"
              class="input-control w-full rounded-xl py-3.5 pl-10 pr-20 text-sm text-slate-900" />
            <div class="absolute right-2 top-1/2 flex -translate-y-1/2 gap-1">
              <button v-if="inputUrl" type="button" class="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
                @click="clearInput">清空</button>
              <button v-else type="button" class="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50"
                @click="pasteClipboard">
                <LearnIcon name="clipboard" :size="13" /> 粘贴
              </button>
            </div>
          </div>
          <button type="submit" :disabled="parsing || !inputUrl.trim()"
            class="btn-primary inline-flex min-h-[48px] items-center justify-center gap-2 rounded-xl px-6 text-sm font-bold">
            <LearnIcon :name="parsing ? 'loader' : 'sparkles'" :size="17" :class="{ 'animate-spin': parsing }" />
            <span>{{ parsing ? '正在载入视频…' : '进入学习工作台' }}</span>
          </button>
        </form>
        <p role="alert" v-if="parseError" class="mt-2.5 flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600 sm:text-sm">
          <LearnIcon name="alert" :size="15" class="shrink-0" /> {{ parseError }}
        </p>
      </div>

      <!-- Empty Guide Cards before video loaded -->
      <div v-if="!info && !parsing" class="mx-auto mt-8 grid max-w-5xl gap-4 sm:grid-cols-3">
        <div v-for="card in [
          ['sparkles', '多视角结构化总结', '支持通用精读、课堂笔记、深度拆解三种视角，超过 1 小时课程自动分段提炼不丢结尾。'],
          ['mindmap', '交互式知识思维导图', '一键把冗长视频转化为清晰脑图，支持缩放折叠与导出高清 PNG / SVG / Markdown。'],
          ['chat', '基于原片的 AI 追问', '自动推荐高价值追问问题，针对未听懂的细节随时提问，回答附带可点击时间戳溯源。'],
        ]" :key="card[1]" class="glass-card rounded-2xl p-5 text-left">
          <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
            <LearnIcon :name="card[0]" :size="20" />
          </span>
          <h3 class="mt-3 text-base font-bold text-slate-900">{{ card[1] }}</h3>
          <p class="mt-1.5 text-xs leading-6 text-slate-500">{{ card[2] }}</p>
        </div>
      </div>

      <!-- Split-Screen Learning Workbench -->
      <div v-if="info" class="mt-6 grid grid-cols-1 items-start gap-5 lg:grid-cols-12">
        <!-- Left Column: Video Player + Searchable Transcript -->
        <div class="space-y-4 lg:sticky lg:top-20 lg:col-span-5">
          <div class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <!-- Media Player -->
            <div class="aspect-video w-full bg-slate-950">
              <video v-if="info.direct?.url" ref="native-video" :src="info.direct.url" :poster="thumbUrl"
                controls preload="metadata" referrerpolicy="no-referrer" class="h-full w-full object-contain"></video>
              <iframe v-else-if="bilibiliIframeSrc" :key="bilibiliIframeSrc" :src="bilibiliIframeSrc"
                class="h-full w-full border-0" allow="autoplay; fullscreen"
                referrerpolicy="no-referrer" title="Bilibili 视频播放器"></iframe>
              <iframe v-else-if="youtubeIframeSrc" :key="youtubeIframeSrc" :src="youtubeIframeSrc"
                class="h-full w-full border-0" allow="autoplay; encrypted-media; fullscreen"
                title="YouTube 视频播放器"></iframe>
              <div v-else class="relative flex h-full w-full items-center justify-center">
                <img v-if="thumbUrl" :src="thumbUrl" :alt="info.title" referrerpolicy="no-referrer" class="h-full w-full object-cover opacity-70" />
                <a :href="info.url" target="_blank" rel="noopener"
                  class="absolute inline-flex items-center gap-1.5 rounded-full bg-white/95 px-4 py-2 text-xs font-bold text-slate-900 shadow-lg hover:bg-white">
                  <LearnIcon name="external" :size="14" /> 打开原视频观看
                </a>
              </div>
            </div>

            <div class="p-4">
              <h2 class="line-clamp-2 text-sm font-bold leading-snug text-slate-900 sm:text-base">{{ info.title }}</h2>
              <div class="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                <div class="flex flex-wrap items-center gap-2">
                  <span v-if="info.platform" class="rounded bg-slate-100 px-2 py-0.5 font-medium text-slate-700">{{ info.platform }}</span>
                  <span v-if="info.uploader">{{ info.uploader }}</span>
                  <span v-if="info.duration">· {{ fmt.duration(info.duration) }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <RouterLink :to="{ path: '/', query: { url: info.url } }"
                    class="font-semibold text-indigo-600 hover:underline">下载此视频 →</RouterLink>
                </div>
              </div>
              <audio v-if="!info.direct?.url && !bilibiliIframeSrc && !youtubeIframeSrc && info.audio_url"
                ref="native-audio" :src="info.audio_url" controls preload="none" referrerpolicy="no-referrer" class="mt-3 w-full"></audio>
            </div>
          </div>

          <LearnTranscript :info="info" :external-result="syncedResult"
            @result="(val) => { transcriptResult = val }"
            @seek="handleSeek"
            @notify="showToast" />
        </div>

        <!-- Right Column: AI Learning Suite -->
        <div class="lg:col-span-7">
          <AiLearningPanel :info="info" :transcript="transcriptTimedText"
            :external-seek="true" :workbench-mode="true"
            @seek="handleSeek"
            @notify="showToast"
            @transcribed="onPanelTranscribed" />
        </div>
      </div>
    </div>
  </section>
</template>
