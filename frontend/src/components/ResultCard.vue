<script setup>
import { computed, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import Icon from './Icon.vue'
import JobProgress from './JobProgress.vue'
import TranscriptPanel from './TranscriptPanel.vue'
import AiLearningPanel from '../learning/AiLearningPanel.vue'
import { extractBilibiliBvid, extractYoutubeId, formatTs, platformTimeUrl } from '../learning/learnApi.js'
import { api, fileUrl, fmt, pollJob, triggerDownload } from '../api.js'
import { ui } from '../store.js'

const props = defineProps({
  info: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  mode: { type: String, default: 'video' },
  activeView: { type: String, default: 'download' },
  autoSummarizeSeq: { type: Number, default: 0 },
})
const emit = defineEmits(['update:activeView'])

const downloadVideoEl = useTemplateRef('download-video')
const aiVideoEl = useTemplateRef('ai-video')
const aiSeekStatus = ref('')
const embedSeekSec = ref(0)
const embedAutoplay = ref(false)

const quality = ref(null)
const videoJob = ref(null)
const audioJob = ref(null)
const error = ref('')

const transcriptText = ref('')
const timedTranscriptText = ref('')
const syncedTranscriptResult = ref(null)
const showTimestamps = ref(false)

const exportOpen = ref(false)
const exportFormat = ref('txt')

const toast = ref({ show: false, message: '', type: 'success' })
let toastTimer = null
let stopVideo = null
let stopAudio = null
const videoSubmitting = ref(false)
const audioSubmitting = ref(false)
let requestVersion = 0

function notify(message, type = 'success', duration = 2600) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { show: true, message, type }
  toastTimer = setTimeout(() => { toast.value.show = false }, duration)
}

const qualities = computed(() => props.info?.qualities || [])
const thumb = computed(() => props.info?.thumbnail?.replace(/^http:\/\//, 'https://') || '')

const imageList = computed(() => {
  const imgs = (props.info?.images || []).map((u) => u?.replace(/^http:\/\//, 'https://')).filter(Boolean)
  if (!imgs.length && thumb.value) return [thumb.value]
  return imgs
})

const contentText = computed(() => {
  if (!props.info) return ''
  const desc = (props.info.description || '').trim()
  if (desc) return desc
  return props.info.title || ''
})

function extractTagsFromText(...texts) {
  const topicRe = /#([^#\n]+?)\[话题\]#/g
  const hashRe = /(?:^|\s)#([^\s#]+)/g
  const trailRe = /[.,!?;:，。！？；：、…]+$/u
  const out = []
  const seen = new Set()
  const add = (raw) => {
    const t = String(raw || '').replace(trailRe, '').replace(/^#+/, '').trim()
    if (t && !seen.has(t)) {
      seen.add(t)
      out.push(t)
    }
  }
  for (const txt of texts) {
    if (!txt) continue
    const cleaned = String(txt).replace(topicRe, (_, g1) => { add(g1); return ' ' })
    hashRe.lastIndex = 0
    let m
    while ((m = hashRe.exec(cleaned)) !== null) add(m[1])
  }
  for (const t of props.info?.tags || []) add(t)
  return out
}

const tags = computed(() => extractTagsFromText(props.info?.title, props.info?.description))

const videoPreviewUrl = computed(() => {
  if (videoJob.value?.ready) return fileUrl(videoJob.value.id)
  return props.info?.direct?.url || ''
})

const bvid = computed(() => extractBilibiliBvid(props.info?.url || ''))
const youtubeId = computed(() => extractYoutubeId(props.info?.url || ''))

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

const audioPreviewUrl = computed(() => {
  if (audioJob.value?.ready) return fileUrl(audioJob.value.id)
  return props.info?.audio_url || props.info?.direct?.url || ''
})

const videoDownloading = computed(() => videoSubmitting.value || videoJob.value && !['done', 'error'].includes(videoJob.value.status))
const audioDownloading = computed(() => audioSubmitting.value || audioJob.value && !['done', 'error'].includes(audioJob.value.status))

const displayedTranscript = computed(() => {
  if (showTimestamps.value && timedTranscriptText.value) return timedTranscriptText.value
  return transcriptText.value
})

watch(() => props.info, (info) => {
  requestVersion++
  videoSubmitting.value = false
  audioSubmitting.value = false
  stopVideo?.()
  stopAudio?.()
  videoJob.value = null
  audioJob.value = null
  error.value = ''
  aiSeekStatus.value = ''
  embedSeekSec.value = 0
  embedAutoplay.value = false
  syncedTranscriptResult.value = null
  if (!info) return
  quality.value = (info.qualities || []).find((q) => q.height <= 1080)?.height ?? info.qualities?.[0]?.height ?? null
  transcriptText.value = ''
  timedTranscriptText.value = ''
}, { immediate: true })

watch(() => props.activeView, (view) => {
  if (view === 'ai') {
    downloadVideoEl.value?.pause?.()
  } else {
    aiVideoEl.value?.pause?.()
  }
})

function onAiTranscribed(res) {
  if (!res) return
  syncedTranscriptResult.value = res
  transcriptText.value = res.text || ''
  timedTranscriptText.value = res.timed_text || ''
}

function seekAiVideo(seconds) {
  const sec = Math.max(0, Math.floor(Number(seconds) || 0))
  const tsLabel = formatTs(sec)
  const totalLabel = props.info?.duration ? ` / ${fmt.duration(props.info.duration)}` : ''
  aiSeekStatus.value = `▶ 已跳播 · ${tsLabel}${totalLabel}`
  const v = aiVideoEl.value
  if (v && v.getAttribute('src')) {
    v.currentTime = sec
    v.play?.().catch(() => {})
    notify(`🎯 左侧预览小窗已跳播至 ${tsLabel}`, 'success')
    return
  }
  if (bvid.value || youtubeId.value) {
    embedSeekSec.value = sec
    embedAutoplay.value = true
    notify(`🎯 左侧预览小窗已跳播至 ${tsLabel}`, 'success')
    return
  }
  if (props.info?.url) {
    window.open(platformTimeUrl(props.info.url, sec), '_blank', 'noopener')
    notify(`已在原平台打开 ${tsLabel} 处`, 'success')
  }
}

async function copyText(text, label = '已复制到剪贴板') {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    notify(label, 'success')
  } catch {
    notify('复制失败，请手动复制', 'error')
  }
}

function copyAllTags() {
  if (!tags.value.length) return
  copyText(tags.value.map((t) => `#${t}`).join(' '), '已复制全部话题到剪贴板')
}

function copyVideoLink() {
  const link = videoPreviewUrl.value || props.info?.url || ''
  copyText(link, '已复制视频链接到剪贴板')
}

function copyAllImageLinks() {
  if (!imageList.value.length) return
  copyText(imageList.value.join('\n'), `已复制 ${imageList.value.length} 个链接到剪贴板`)
}

async function startVideoDownload() {
  if (!props.info || videoDownloading.value) return
  error.value = ''
  videoSubmitting.value = true
  const current = requestVersion
  stopVideo?.()
  try {
    const created = await api.download({ url: props.info.url, quality: quality.value, kind: 'video' })
    if (current !== requestVersion) return
    videoJob.value = created
    stopVideo = pollJob(created.id, (j) => {
      const prevStatus = videoJob.value?.status
      videoJob.value = { ...videoJob.value, ...j }
      if (j.status === 'done' && prevStatus !== 'done') {
        triggerDownload(fileUrl(j.id), j.filename || 'video.mp4')
        notify('视频已准备就绪，开始下载', 'success')
      } else if (j.status === 'error') {
        notify(j.error || '视频下载失败', 'error')
      }
    })
  } catch (e) {
    if (current !== requestVersion) return
    error.value = e.message
    notify(e.message, 'error')
  } finally {
    if (current === requestVersion) videoSubmitting.value = false
  }
}

async function startAudioDownload() {
  if (!props.info || audioDownloading.value) return
  error.value = ''
  audioSubmitting.value = true
  const current = requestVersion
  stopAudio?.()
  try {
    const created = await api.download({ url: props.info.url, quality: null, kind: 'audio' })
    if (current !== requestVersion) return
    audioJob.value = created
    stopAudio = pollJob(created.id, (j) => {
      const prevStatus = audioJob.value?.status
      audioJob.value = { ...audioJob.value, ...j }
      if (j.status === 'done' && prevStatus !== 'done') {
        triggerDownload(fileUrl(j.id), j.filename || 'audio.mp3')
        notify('音频已准备就绪，开始下载', 'success')
      } else if (j.status === 'error') {
        notify(j.error || '音频提取失败', 'error')
      }
    })
  } catch (e) {
    if (current !== requestVersion) return
    error.value = e.message
    notify(e.message, 'error')
  } finally {
    if (current === requestVersion) audioSubmitting.value = false
  }
}

async function downloadImage(imgUrl, idx = 0) {
  if (!imgUrl) return
  const filename = `image-${idx + 1}.jpg`
  try {
    const res = await fetch(imgUrl, { mode: 'cors', credentials: 'omit', referrerPolicy: 'no-referrer' })
    if (!res.ok) throw new Error('fetch failed')
    const blob = await res.blob()
    const blobUrl = URL.createObjectURL(blob)
    triggerDownload(blobUrl, filename)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1500)
    notify(`${filename} 下载成功`, 'success')
  } catch {
    window.open(imgUrl, '_blank', 'noopener')
  }
}

function downloadAllImages() {
  imageList.value.forEach((img, idx) => {
    setTimeout(() => downloadImage(img, idx), idx * 350)
  })
}

function handleExport() {
  if (!props.info) return
  const title = props.info.title || '提取结果'
  const safeName = title.replace(/[\\/:*?"<>|\r\n]+/g, '_').slice(0, 60) || 'extract-result'
  const tagsLine = tags.value.length ? tags.value.map((t) => `#${t}`).join(' ') : ''
  let content = ''
  let ext = 'txt'
  if (exportFormat.value === 'md') {
    ext = 'md'
    content = [
      `# ${title}`,
      '',
      `- 平台：${props.info.platform || '-'}`,
      props.info.uploader ? `- 作者：${props.info.uploader}` : '',
      `- 原链接：${props.info.url || '-'}`,
      '',
      '## 标题与简介',
      contentText.value || '-',
      tagsLine ? `\n**话题标签**：${tagsLine}` : '',
      '',
      '## 视频文案',
      displayedTranscript.value || '暂未识别',
    ].filter((l) => l !== '').join('\n')
  } else {
    ext = 'txt'
    content = [
      `【标题】${title}`,
      props.info.uploader ? `【作者】${props.info.uploader}` : '',
      `【原链接】${props.info.url || '-'}`,
      '',
      '【标题与简介】',
      contentText.value || '-',
      tagsLine ? `\n【话题】${tagsLine}` : '',
      '',
      '【视频文案】',
      displayedTranscript.value || '暂未识别',
    ].filter((l) => l !== '').join('\n')
  }
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  triggerDownload(url, `${safeName}.${ext}`)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
  exportOpen.value = false
  notify('导出成功', 'success')
}

onUnmounted(() => {
  requestVersion++
  stopVideo?.()
  stopAudio?.()
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <div>
    <!-- Toast Notification -->
    <Transition
      enter-active-class="transition ease-out duration-300"
      enter-from-class="opacity-0 translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition ease-in duration-200"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-2"
    >
      <div v-if="toast.show" class="fixed left-1/2 top-20 z-50 w-full max-w-md -translate-x-1/2 px-4">
        <div
          class="flex items-center gap-3 rounded-lg border-l-4 p-4 shadow-2xl"
          :class="toast.type === 'success' ? 'border-green-500 bg-green-50' : toast.type === 'error' ? 'border-red-500 bg-red-50' : 'border-blue-500 bg-blue-50'"
        >
          <div
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white"
            :class="toast.type === 'success' ? 'bg-green-500' : toast.type === 'error' ? 'bg-red-500' : 'bg-blue-500'"
          >
            <Icon :name="toast.type === 'success' ? 'check' : toast.type === 'error' ? 'x' : 'alert'" :size="14" />
          </div>
          <p
            class="flex-1 text-sm font-medium"
            :class="toast.type === 'success' ? 'text-green-800' : toast.type === 'error' ? 'text-red-800' : 'text-blue-800'"
          >
            {{ toast.message }}
          </p>
          <button
            type="button"
            class="shrink-0 rounded-full p-1 transition-colors hover:bg-white/50"
            :class="toast.type === 'success' ? 'text-green-600' : toast.type === 'error' ? 'text-red-600' : 'text-blue-600'"
            @click="toast.show = false"
          >
            <Icon name="x" :size="16" />
          </button>
        </div>
      </div>
    </Transition>

    <!-- Main Extraction Result Card (AnyToCopy layout) -->
    <div class="overflow-hidden rounded-2xl border border-gray-100 bg-white text-left shadow-[0_18px_60px_rgba(15,23,42,0.08)] sm:rounded-3xl">
      <!-- Top Header Bar -->
      <div class="flex flex-col gap-3 border-b border-gray-100 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-7">
        <div class="flex items-center gap-3">
          <div class="h-8 w-1.5 rounded-full bg-gradient-to-b from-blue-600 to-purple-600"></div>
          <div>
            <div class="flex flex-wrap items-center gap-2.5">
              <h3 class="text-xl font-bold text-gray-950">提取结果</h3>
              <div class="inline-flex items-center rounded-xl border border-slate-200 bg-slate-100/90 p-0.5 text-xs font-bold">
                <button
                  type="button"
                  class="inline-flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-1 transition"
                  :class="activeView !== 'ai' ? 'bg-blue-600 text-white shadow-xs' : 'text-slate-600 hover:text-blue-600'"
                  @click="emit('update:activeView', 'download')"
                >
                  <Icon name="download" :size="13" />
                  <span>素材与文案下载</span>
                </button>
                <button
                  type="button"
                  class="inline-flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-1 transition"
                  :class="activeView === 'ai' ? 'bg-violet-600 text-white shadow-xs' : 'text-slate-600 hover:text-violet-600'"
                  @click="emit('update:activeView', 'ai')"
                >
                  <Icon name="sparkles" :size="13" />
                  <span>AI 视频总结</span>
                </button>
              </div>
            </div>
            <p class="mt-0.5 text-sm text-gray-500">文案、媒体素材和导出操作已整理完成（可在上方输入框选项卡随时切换至 AI 视频总结）</p>
          </div>
        </div>
        <div v-if="info" class="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
          <button
            type="button"
            class="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-4 text-sm font-semibold text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900 sm:w-auto"
            @click="exportOpen = true"
          >
            <Icon name="download" :size="15" />
            <span>导出</span>
          </button>
          <div class="flex flex-wrap items-center gap-2">
            <button
              type="button"
              class="inline-flex items-center justify-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-600 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-100 hover:text-indigo-700"
              @click="ui.openUpgrade('加入选题')"
            >
              <Icon name="folder" :size="16" />
              <span>加入选题</span>
            </button>
            <RouterLink
              :to="{ path: '/ai', query: { url: info.url } }"
              class="inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50"
            >
              <Icon name="edit" :size="15" />
              <span>AI 创作</span>
            </RouterLink>
            <RouterLink
              :to="{ path: '/learn', query: { url: info.url } }"
              class="inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-md shadow-indigo-600/25 transition hover:bg-indigo-500"
            >
              <Icon name="sparkles" :size="16" />
              <span>↗ 全屏工作台</span>
            </RouterLink>
          </div>
        </div>
      </div>

      <!-- Card Body -->
      <div class="space-y-4 p-4 sm:p-5 md:p-6">
        <!-- Loading / Waiting State -->
        <div v-if="loading" class="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div class="flex items-center gap-3">
            <div class="inline-block h-6 w-6 animate-spin rounded-full border-b-2 border-blue-600"></div>
            <div class="flex-1">
              <div class="font-semibold text-blue-800">正在提取中</div>
              <div class="mt-1 text-sm text-blue-600">正在提取内容，请稍候...</div>
            </div>
          </div>
        </div>

        <template v-else-if="info">
          <!-- VIEW 1: 素材与文案下载 -->
          <div v-show="activeView !== 'ai'" class="space-y-4">
            <!-- 1. 标题与简介 -->
            <div class="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm sm:p-5">
              <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h4 class="text-base font-bold text-gray-900">标题与简介</h4>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <RouterLink
                    :to="{ path: '/ai', query: { url: info.url } }"
                    class="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 text-xs font-semibold text-indigo-600 transition hover:bg-indigo-100"
                  >
                    <Icon name="edit" :size="15" />
                    <span>生成爆款</span>
                  </RouterLink>
                </div>
              </div>

              <div class="space-y-3">
                <!-- Title row -->
                <div v-if="info.title" class="flex items-start justify-between gap-3">
                  <p class="text-base font-semibold leading-relaxed text-gray-900 sm:text-lg">{{ info.title }}</p>
                  <button
                    type="button"
                    title="复制标题"
                    aria-label="复制标题"
                    class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
                    @click="copyText(info.title, '标题已复制到剪贴板')"
                  >
                    <Icon name="copy" :size="16" />
                  </button>
                </div>

                <!-- Content / Description row -->
                <div v-if="contentText" class="flex items-start justify-between gap-3 border-t border-gray-100 pt-3">
                  <p class="flex-1 whitespace-pre-wrap leading-7 text-gray-700">{{ contentText }}</p>
                  <button
                    type="button"
                    title="复制正文"
                    aria-label="复制正文"
                    class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
                    @click="copyText(contentText, '正文已复制到剪贴板')"
                  >
                    <Icon name="copy" :size="16" />
                  </button>
                </div>

                <!-- Hashtags row -->
                <div v-if="tags.length" class="flex flex-wrap items-center gap-2 border-t border-gray-100 pt-3">
                  <button
                    v-for="tag in tags"
                    :key="tag"
                    type="button"
                    :title="`复制话题 #${tag}`"
                    :aria-label="`复制话题 #${tag}`"
                    class="inline-flex items-center rounded-full border border-indigo-100 bg-indigo-50 px-2.5 py-1 text-xs text-indigo-500 transition hover:border-indigo-200 hover:bg-indigo-100 hover:text-indigo-600"
                    @click="copyText(`#${tag}`, `已复制话题 #${tag}`)"
                  >
                    #{{ tag }}
                  </button>
                  <button
                    type="button"
                    title="复制全部话题"
                    aria-label="复制全部话题"
                    class="inline-flex h-7 w-7 items-center justify-center rounded-full text-indigo-400 transition hover:bg-indigo-50 hover:text-indigo-600"
                    @click="copyAllTags"
                  >
                    <Icon name="copy" :size="15" />
                  </button>
                </div>
              </div>
            </div>

            <!-- 2. 视频内容 -->
            <div class="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm sm:p-4">
              <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h4 class="text-base font-bold text-gray-900 sm:text-lg">视频内容</h4>
                  <p class="mt-0.5 text-sm text-gray-500">
                    共 1 个视频素材
                    <span v-if="info.platform" class="ml-1.5 text-xs text-gray-400">· {{ info.platform }}</span>
                    <span v-if="info.duration" class="ml-1.5 text-xs text-gray-400">· {{ fmt.duration(info.duration) }}</span>
                  </p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <!-- Quality selector if multiple qualities exist -->
                  <select
                    v-if="qualities.length"
                    v-model="quality"
                    aria-label="选择视频清晰度"
                    class="h-9 rounded-lg border border-gray-200 bg-white px-2.5 text-xs font-semibold text-gray-700 shadow-sm focus:border-indigo-400 focus:outline-none sm:text-sm"
                  >
                    <option v-for="q in qualities" :key="q.height" :value="q.height">
                      {{ q.label }}{{ q.size ? ` (${fmt.size(q.size)})` : '' }}
                    </option>
                  </select>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 text-xs font-semibold text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900 sm:px-4 sm:text-sm"
                    @click="copyVideoLink"
                  >
                    <Icon name="copy" :size="15" />
                    <span>复制全部链接</span>
                  </button>
                  <button
                    type="button"
                    :disabled="videoDownloading"
                    class="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 text-xs font-semibold text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-50 sm:px-4 sm:text-sm"
                    @click="startVideoDownload"
                  >
                    <Icon name="download" :size="15" :class="{ 'animate-pulse': videoDownloading }" />
                    <span>{{ videoDownloading ? `下载中 ${Math.round(videoJob?.progress || 0)}%` : '下载高清视频' }}</span>
                  </button>
                </div>
              </div>

              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <div class="rounded-xl border border-gray-200 bg-gray-50 p-2">
                  <video
                    v-if="videoPreviewUrl"
                    ref="download-video"
                    :src="videoPreviewUrl"
                    :poster="thumb"
                    controls
                    preload="metadata"
                    class="mb-2 w-full rounded-lg bg-black"
                    style="max-height: 160px"
                    referrerpolicy="no-referrer"
                  ></video>
                  <iframe
                    v-else-if="bilibiliIframeSrc && activeView !== 'ai'"
                    :src="bilibiliIframeSrc"
                    class="mb-2 aspect-video w-full rounded-lg border-0 bg-black"
                    style="max-height: 160px"
                    allowfullscreen
                    allow="autoplay; fullscreen"
                    referrerpolicy="no-referrer"
                    title="Bilibili 视频预览"
                  ></iframe>
                  <iframe
                    v-else-if="youtubeIframeSrc && activeView !== 'ai'"
                    :src="youtubeIframeSrc"
                    class="mb-2 aspect-video w-full rounded-lg border-0 bg-black"
                    style="max-height: 160px"
                    allowfullscreen
                    allow="autoplay; encrypted-media"
                    title="YouTube 视频预览"
                  ></iframe>
                  <video
                    v-else
                    ref="download-video"
                    :poster="thumb"
                    controls
                    preload="none"
                    class="mb-2 w-full rounded-lg bg-black"
                    style="max-height: 160px"
                    referrerpolicy="no-referrer"
                  ></video>
                  <div class="mt-2 flex gap-2">
                    <button
                      type="button"
                      :disabled="videoDownloading"
                      class="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 text-center text-sm font-medium text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-60"
                      @click="startVideoDownload"
                    >
                      <Icon name="download" :size="15" :class="{ 'animate-pulse': videoDownloading }" />
                      <span>
                        {{ videoDownloading ? (videoJob?.status === 'processing' ? '合并中…' : `下载中 ${Math.round(videoJob?.progress || 0)}%`) : '下载视频' }}
                      </span>
                    </button>
                    <button
                      type="button"
                      class="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 text-center text-sm font-medium text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
                      @click="copyVideoLink"
                    >
                      <Icon name="copy" :size="15" />
                      <span>复制链接</span>
                    </button>
                  </div>
                </div>
              </div>
              <JobProgress v-if="videoJob && (videoDownloading || videoJob.status === 'error')" :job="videoJob" class="mt-3" />
            </div>

            <!-- 3. 音频内容 -->
            <div v-if="info.has_audio !== false" class="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm sm:p-4">
              <div class="mb-3 flex items-center justify-between">
                <h4 class="text-lg font-semibold text-gray-800">音频内容</h4>
                <button
                  type="button"
                  :disabled="audioDownloading"
                  class="inline-flex items-center gap-1.5 text-sm font-medium text-gray-500 transition-colors hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-60"
                  @click="startAudioDownload"
                >
                  <Icon name="download" :size="15" :class="{ 'animate-pulse': audioDownloading }" />
                  <span>{{ audioDownloading ? `提取中 ${Math.round(audioJob?.progress || 0)}%` : '下载音频' }}</span>
                </button>
              </div>
              <div class="rounded-xl border border-gray-200 bg-gray-50 p-4">
                <div v-if="audioDownloading && !audioPreviewUrl" class="flex items-center justify-center py-6">
                  <div class="mr-3 inline-block h-7 w-7 animate-spin rounded-full border-b-2 border-blue-600"></div>
                  <span class="font-medium text-blue-600">音频内容提取中...</span>
                </div>
                <audio
                  v-else
                  :src="audioPreviewUrl"
                  controls
                  preload="none"
                  class="w-full"
                  referrerpolicy="no-referrer"
                ></audio>
              </div>
            </div>

            <TranscriptPanel
              :info="info"
              :active="activeView !== 'ai'"
              :external-result="syncedTranscriptResult"
              @notify="notify"
              @update:timestamps="showTimestamps = $event"
              @result="(value) => { transcriptText = value?.text || ''; timedTranscriptText = value?.timed_text || '' }"
            />

            <!-- 5. 图片内容 -->
            <div v-if="imageList.length" class="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm sm:p-4">
              <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h4 class="text-base font-bold text-gray-900 sm:text-lg">图片内容</h4>
                  <p class="mt-0.5 text-sm text-gray-500">共 {{ imageList.length }} 张图片素材</p>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button
                    type="button"
                    class="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 text-xs font-semibold text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900 sm:px-4 sm:text-sm"
                    @click="copyAllImageLinks"
                  >
                    <Icon name="copy" :size="15" />
                    <span>复制全部链接</span>
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 text-xs font-semibold text-gray-700 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900 sm:px-4 sm:text-sm"
                    @click="downloadAllImages"
                  >
                    <Icon name="download" :size="15" />
                    <span>批量下载图片</span>
                  </button>
                  <RouterLink
                    :to="{ path: '/ai', query: { url: info.url } }"
                    class="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 text-xs font-semibold text-indigo-600 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-100 sm:px-4 sm:text-sm"
                  >
                    <Icon name="file" :size="15" />
                    <span>图片文案提取</span>
                  </RouterLink>
                </div>
              </div>

              <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-4">
                <div
                  v-for="(img, idx) in imageList"
                  :key="idx"
                  class="group relative overflow-hidden rounded-2xl border border-gray-200 bg-gray-50"
                >
                  <img
                    :src="img"
                    :alt="`图片 ${idx + 1}`"
                    class="h-auto w-full object-contain"
                    referrerpolicy="no-referrer"
                  />
                  <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-2 opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      type="button"
                      class="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-white/90 px-3 py-1 text-center text-sm font-medium text-gray-700 transition hover:bg-white"
                      @click="downloadImage(img, idx)"
                    >
                      <Icon name="download" :size="14" />
                      <span>下载图片</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- VIEW 2: AI 视频总结专属视图（左侧联动视频小窗 + 右侧完整 AI 精读面板） -->
          <div v-show="activeView === 'ai'" class="grid grid-cols-1 items-start gap-[18px] min-[960px]:grid-cols-[360px_1fr]">
            <!-- Left Mini Sticky Video Preview + Quick Download -->
            <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm min-[960px]:sticky min-[960px]:top-20">
              <div class="mb-2.5 flex items-center justify-between gap-2">
                <div class="text-sm font-bold text-slate-900">🎬 同屏联动预览</div>
                <span v-if="aiSeekStatus" class="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-600">
                  {{ aiSeekStatus }}
                </span>
                <span v-else-if="info.duration" class="text-xs font-medium text-slate-400">
                  ▶ 00:00 / {{ fmt.duration(info.duration) }}
                </span>
              </div>
              <video
                v-if="videoPreviewUrl"
                ref="ai-video"
                :src="videoPreviewUrl"
                :poster="thumb"
                controls
                preload="metadata"
                class="aspect-video w-full rounded-[14px] bg-slate-950 object-contain"
                referrerpolicy="no-referrer"
              ></video>
              <iframe
                v-else-if="bilibiliIframeSrc && activeView === 'ai'"
                :key="bilibiliIframeSrc"
                :src="bilibiliIframeSrc"
                class="aspect-video w-full rounded-[14px] border-0 bg-slate-950"
                allowfullscreen
                allow="autoplay; fullscreen"
                referrerpolicy="no-referrer"
                title="Bilibili 同屏预览"
              ></iframe>
              <iframe
                v-else-if="youtubeIframeSrc && activeView === 'ai'"
                :key="youtubeIframeSrc"
                :src="youtubeIframeSrc"
                class="aspect-video w-full rounded-[14px] border-0 bg-slate-950"
                allowfullscreen
                allow="autoplay; encrypted-media"
                title="YouTube 同屏预览"
              ></iframe>
              <video
                v-else
                ref="ai-video"
                :poster="thumb"
                controls
                preload="none"
                class="aspect-video w-full rounded-[14px] bg-slate-950 object-contain"
                referrerpolicy="no-referrer"
              ></video>
              <p v-if="info.title" class="mt-2.5 line-clamp-2 text-xs font-semibold leading-relaxed text-slate-700">
                {{ info.title }}
              </p>
              <p class="mt-1 text-xs text-slate-400">点击右侧时间戳自动跳播</p>
              <div class="mt-3 flex gap-2">
                <button
                  type="button"
                  :disabled="videoDownloading"
                  class="btn-primary inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-[10px] px-3 text-[13px] font-bold disabled:cursor-not-allowed disabled:opacity-60"
                  @click="startVideoDownload"
                >
                  <Icon name="download" :size="14" :class="{ 'animate-pulse': videoDownloading }" />
                  <span>
                    {{ videoDownloading ? (videoJob?.status === 'processing' ? '合并中…' : `下载中 ${Math.round(videoJob?.progress || 0)}%`) : '⬇ 顺手下载视频' }}
                  </span>
                </button>
                <button
                  type="button"
                  class="inline-flex h-9 items-center justify-center rounded-[10px] border border-slate-200 bg-white px-3.5 text-[13px] font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
                  @click="emit('update:activeView', 'download')"
                >
                  更多素材
                </button>
              </div>
              <JobProgress v-if="videoJob && (videoDownloading || videoJob.status === 'error')" :job="videoJob" class="mt-3" />
            </div>

            <!-- Right Full AI Panel -->
            <div class="min-w-0">
              <AiLearningPanel
                :info="info"
                :transcript="timedTranscriptText"
                :external-seek="true"
                :auto-run-trigger="autoSummarizeSeq"
                @seek="seekAiVideo"
                @notify="notify"
                @transcribed="onAiTranscribed"
              />
            </div>
          </div>

          <p v-if="error" class="flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
            <Icon name="alert" :size="16" /> {{ error }}
          </p>
        </template>
      </div>
    </div>

    <!-- Export Modal -->
    <Transition
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
      enter-active-class="transition"
      leave-active-class="transition"
    >
      <div
        v-if="exportOpen"
        class="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
        @click.self="exportOpen = false"
      >
        <div class="w-full max-w-md rounded-2xl bg-white p-6 text-left shadow-2xl">
          <div class="flex items-center justify-between">
            <h3 class="text-lg font-bold text-gray-900">选择导出格式</h3>
            <button type="button" class="p-1 text-gray-400 hover:text-gray-600" @click="exportOpen = false">
              <Icon name="x" :size="18" />
            </button>
          </div>
          <p class="mt-1 text-sm text-gray-500">导出文件将包含任务信息和提取文案。</p>
          <div class="mt-4 space-y-2.5">
            <label
              v-for="opt in [['txt', '纯文本文件 (.txt)'], ['md', '结构化 .md 文件 (.md)']]"
              :key="opt[0]"
              class="flex cursor-pointer items-center justify-between rounded-xl border p-3.5 text-sm font-medium transition"
              :class="exportFormat === opt[0] ? 'border-indigo-500 bg-indigo-50/60 text-indigo-700' : 'border-gray-200 hover:border-gray-300 text-gray-700'"
            >
              <span>{{ opt[1] }}</span>
              <input v-model="exportFormat" type="radio" :value="opt[0]" class="accent-indigo-600" />
            </label>
          </div>
          <div class="mt-6 flex justify-end gap-2">
            <button
              type="button"
              class="rounded-xl border border-gray-200 px-4 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50"
              @click="exportOpen = false"
            >
              取消
            </button>
            <button
              type="button"
              class="rounded-xl bg-indigo-600 px-5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500"
              @click="handleExport"
            >
              确认导出
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
