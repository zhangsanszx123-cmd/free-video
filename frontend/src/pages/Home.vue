<script setup>
import { onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import ResultCard from '../components/ResultCard.vue'
import FaqList from '../components/FaqList.vue'
import { api } from '../api.js'
import { account, openAuth } from '../account.js'
import { useParseRequest } from '../useParseRequest.js'
import { faqs, features, platformTable, platforms, scenarios, steps } from '../data.js'

const urlInputEl = useTemplateRef('url-input')
const url = ref('')
const { loading, parse: requestParse, cancel: cancelParse } = useParseRequest()
const serviceState = ref('checking')
let healthController
let healthTimer
let disposed = false
const error = ref('')
const info = ref(null)
const parsedUrl = ref('')
const activeView = ref('download')
const autoSummarizeSeq = ref(0)

async function paste() {
  try {
    url.value = await navigator.clipboard.readText()
  } catch {
    error.value = '浏览器不允许读取剪贴板，请长按输入框手动粘贴'
  }
}

const scrollTop = () => window.scrollTo({ top: 0, behavior: 'smooth' })

const route = useRoute()
onMounted(async () => {
  checkHealth()
  // AI summary requires login; guests opening a shared ?view=ai link fall back to the download view.
  if (route.query.view === 'ai' && (await account.ensure(), account.loggedIn)) activeView.value = 'ai'
  if (disposed) return
  if (route.query.url) {
    url.value = String(route.query.url)
    submitWithView(activeView.value)
  }
})

async function parse() {
  const target = url.value.trim()
  if (!target || loading.value) return false
  error.value = ''
  info.value = null
  try {
    const result = await requestParse(target)
    if (!result) return false
    info.value = result
    parsedUrl.value = target
    return true
  } catch (e) {
    error.value = e.message
    if (e.code === 'GUEST_LIMIT') openAuth({ notice: e.message, onSuccess: () => { if (!disposed) submitWithView(activeView.value) } })
    return false
  }
}

/** AI summary is login-only (backend returns 401 too): guests get the login dialog, then the action resumes. */
async function aiAllowed(resume) {
  await account.ensure()
  if (account.loggedIn || disposed) return account.loggedIn
  openAuth({ notice: '登录后即可使用 AI 视频总结', onSuccess: () => { if (!disposed) resume() } })
  return false
}

async function submitWithView(view = 'download') {
  if (view === 'ai' && !(await aiAllowed(() => submitWithView('ai')))) return
  activeView.value = view
  const target = url.value.trim()
  if (!target) {
    urlInputEl.value?.focus()
    return
  }
  if (loading.value) return
  const needParse = !info.value || parsedUrl.value !== target
  const ok = needParse ? await parse() : true
  if (ok && view === 'ai' && activeView.value === 'ai' && url.value.trim() === target) {
    autoSummarizeSeq.value += 1
  }
}

async function selectTab(view) {
  if (view === 'ai' && !(await aiAllowed(() => selectTab('ai')))) return
  activeView.value = view
  const target = url.value.trim()
  if (!target || loading.value) return
  const needParse = !info.value || parsedUrl.value !== target
  const ok = needParse ? await parse() : true
  if (ok && view === 'ai' && activeView.value === 'ai' && url.value.trim() === target) {
    autoSummarizeSeq.value += 1
  }
}
function clearInput() {
  cancelParse()
  url.value = ''
  info.value = null
  parsedUrl.value = ''
  error.value = ''
}
watch(url, () => { cancelParse(); error.value = '' }, { flush: 'sync' })
async function checkHealth() {
  healthController = new AbortController()
  const timeout = setTimeout(() => healthController.abort(), 5000)
  try {
    const health = await api.health(healthController.signal)
    serviceState.value = health.ok ? 'ready' : 'offline'
  } catch { serviceState.value = 'offline' }
  finally { clearTimeout(timeout) }
  if (!disposed) healthTimer = setTimeout(checkHealth, 30000)
}
onUnmounted(() => { disposed = true; clearTimeout(healthTimer); healthController?.abort() })
</script>

<template>
  <!-- Hero -->
  <section class="hero-bg relative overflow-hidden pb-14 pt-12 sm:pb-20 sm:pt-16 lg:pt-24">
    <div class="pointer-events-none absolute -left-24 top-24 h-72 w-72 rounded-full bg-blue-400/20 blur-3xl"></div>
    <div class="pointer-events-none absolute -right-24 top-10 h-72 w-72 rounded-full bg-violet-400/20 blur-3xl"></div>
    <div class="relative mx-auto max-w-5xl px-4 text-center sm:px-6">
      <div class="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50/90 px-3 py-1 text-xs font-semibold text-amber-700">
        <Icon name="gift" :size="14" /> 游客可免费下载 2 个视频<span class="hidden sm:inline">，登录后不限次数，语音识别按月度额度使用</span>
        <RouterLink to="/pricing" class="text-amber-800 underline-offset-2 hover:underline">查看 →</RouterLink>
      </div>
      <h1 class="mt-5 text-3xl font-extrabold leading-tight tracking-tight text-slate-950 sm:text-5xl lg:text-6xl">
        支持 1800+ 平台<br class="sm:hidden" />
        <span class="text-grad">高清视频一键下载</span>
      </h1>
      <p class="mx-auto mt-5 max-w-3xl text-sm leading-relaxed text-slate-600 sm:text-lg">
        粘贴链接，即可下载抖音、B站、YouTube、TikTok、X、微博等平台的 <b class="text-slate-800">4K 原画视频</b>、
        <b class="text-slate-800">MP3 音频</b>与<b class="text-slate-800">字幕</b>；支持批量打包与 AI 视频总结。电脑、手机都能用。
      </p>

      <!-- Seamless Input Card (max-w-4xl = 896px, Left-aligned inner grid + compact 12px gap + Top-Left / Bottom-Right diagonal balance) -->
      <div class="input-shell mx-auto mt-8 max-w-4xl rounded-[1.75rem] p-4 text-left sm:px-6 sm:pb-5 sm:pt-4">
        <!-- Top Mode Switcher Row (Left-aligned with input box below, no divider line, compact 12px gap) -->
        <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div
            class="inline-flex flex-wrap items-center gap-1.5"
            role="tablist"
            aria-label="核心功能模式切换"
          >
            <!-- Tab 1: 素材与文案下载 -->
            <button
              type="button"
              id="mode-tab-download"
              role="tab"
              :aria-selected="activeView === 'download'"
              :aria-controls="loading || info ? 'result-panel' : undefined"
              class="inline-flex h-10 cursor-pointer items-center gap-2 rounded-xl px-4 text-sm font-extrabold transition-all duration-200 sm:px-6 sm:text-[15px]"
              :class="activeView === 'download'
                ? 'bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 text-white shadow-[0_6px_16px_-4px_rgba(124,58,237,0.55)]'
                : 'bg-purple-50/70 text-slate-700 ring-1 ring-purple-200/80 hover:bg-purple-100/70 hover:text-purple-700'"
              @click="selectTab('download')"
            >
              <Icon name="download" :size="17" :class="activeView === 'download' ? 'text-white' : 'text-violet-600'" />
              <span>素材与文案下载</span>
            </button>

            <!-- Tab 2: AI 视频总结 -->
            <button
              type="button"
              id="mode-tab-ai"
              role="tab"
              :aria-selected="activeView === 'ai'"
              :aria-controls="loading || info ? 'result-panel' : undefined"
              class="inline-flex h-10 cursor-pointer items-center gap-2 rounded-xl px-4 text-sm font-extrabold transition-all duration-200 sm:px-6 sm:text-[15px]"
              :class="activeView === 'ai'
                ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow-[0_6px_16px_-4px_rgba(37,99,235,0.5)]'
                : 'bg-blue-50/70 text-slate-700 ring-1 ring-blue-200/80 hover:bg-blue-100/70 hover:text-blue-700'"
              @click="selectTab('ai')"
            >
              <Icon name="sparkles" :size="17" :class="activeView === 'ai' ? 'text-amber-300' : 'text-blue-600'" />
              <span>AI 视频总结</span>
            </button>
          </div>

          <span role="status" class="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <span class="h-1.5 w-1.5 rounded-full" :class="serviceState === 'ready' ? 'bg-emerald-500' : serviceState === 'offline' ? 'bg-rose-500' : 'bg-amber-500'"></span> {{ serviceState === 'ready' ? '服务可用' : serviceState === 'offline' ? '服务连接失败' : '正在检查服务…' }} · 文件保留 30 分钟
          </span>
        </div>

        <!-- Main Grounded Body: 60px Input + 100% Saturated Vibrant Action Buttons -->
        <form class="flex flex-col gap-3 sm:flex-row sm:items-center" @submit.prevent="submitWithView(activeView)">
          <div class="relative flex-1">
            <Icon name="link" :size="20" class="absolute left-4 top-1/2 -translate-y-1/2 text-indigo-500/80" />
            <input
              ref="url-input"
              aria-label="视频链接或分享口令"
              v-model="url"
              type="text"
              inputmode="url"
              autocomplete="off"
              :placeholder="activeView === 'ai' ? '粘贴视频链接，AI 一键总结' : '粘贴视频链接或分享口令'"
              class="input-control min-h-[60px] w-full rounded-2xl py-4 pl-12 pr-24 text-sm font-medium text-slate-900 placeholder-slate-400 sm:text-base"
            />
            <div class="absolute right-2.5 top-1/2 flex -translate-y-1/2 gap-1">
              <button v-if="url" type="button" class="min-h-11 rounded-xl px-2.5 py-2 text-xs font-medium text-slate-500 hover:bg-slate-100" @click="clearInput">清空</button>
              <button v-else type="button" class="inline-flex items-center gap-1 rounded-xl border border-indigo-100 bg-indigo-50/80 px-3 py-2 text-xs font-semibold text-indigo-600 transition hover:bg-indigo-100" @click="paste">
                <Icon name="clipboard" :size="14" /> 粘贴
              </button>
            </div>
          </div>
          <button
            type="submit"
            :disabled="loading"
            class="inline-flex min-h-[60px] cursor-pointer items-center justify-center gap-2 rounded-2xl px-8 text-base font-extrabold whitespace-nowrap text-white transition-all duration-200 hover:-translate-y-px disabled:cursor-not-allowed disabled:opacity-55 sm:min-w-[164px]"
            :class="activeView === 'ai'
              ? 'bg-gradient-to-br from-blue-600 to-indigo-600 shadow-[0_12px_26px_-8px_rgba(37,99,235,0.6)] hover:shadow-[0_16px_30px_-8px_rgba(37,99,235,0.75)]'
              : 'bg-gradient-to-br from-indigo-600 via-violet-600 to-purple-600 shadow-[0_12px_26px_-8px_rgba(124,58,237,0.65)] hover:shadow-[0_16px_30px_-8px_rgba(124,58,237,0.8)]'"
          >
            <Icon
              :name="loading ? 'loader' : (activeView === 'ai' ? 'sparkles' : 'zap')"
              :size="19"
              :class="{ 'animate-spin': loading }"
            />
            <span>{{ loading ? '解析中…' : (activeView === 'ai' ? 'AI 总结' : '立即解析') }}</span>
          </button>
        </form>

        <!-- Bottom Capability Bar + Mode Hint -->
        <div class="mt-3.5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200/60 pt-3 text-xs">
          <div class="flex flex-wrap items-center gap-2 text-slate-600">
            <span class="inline-flex items-center gap-1 rounded-lg bg-slate-100/90 px-2.5 py-1 font-medium">
              <Icon name="video" :size="13" class="text-blue-600" /> 4K+ 原画画质
            </span>
            <span class="inline-flex items-center gap-1 rounded-lg bg-slate-100/90 px-2.5 py-1 font-medium">
              <Icon name="music" :size="13" class="text-indigo-600" /> 192k 高品质 MP3
            </span>
            <span class="inline-flex items-center gap-1 rounded-lg bg-slate-100/90 px-2.5 py-1 font-medium">
              <Icon name="captions" :size="13" class="text-violet-600" /> 字幕提取 / 转写
            </span>
            <span class="inline-flex items-center gap-1 rounded-lg bg-purple-50/90 px-2.5 py-1 font-medium text-purple-700">
              <Icon name="sparkles" :size="13" class="text-purple-600" /> AI 大纲 · 脑图 · 追问
            </span>
          </div>
          <span class="hidden items-center gap-1 text-slate-400 md:inline-flex">
            {{ activeView === 'ai' ? '已选：AI 视频总结模式 · 自动生成大纲与脑图' : '已选：素材与文案下载模式 · 支持视频 / MP3 / 字幕' }}
          </span>
        </div>
        <p role="alert" v-if="error" class="mt-3 flex items-start gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
          <Icon name="alert" :size="16" class="mt-0.5 shrink-0" /> {{ error }}
        </p>
      </div>

      <!-- Batch extraction entry -->
      <RouterLink
        to="/batch"
        class="batch-banner group mx-auto mt-4 flex max-w-4xl flex-col gap-4 rounded-3xl p-5 text-left sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:py-4.5"
      >
        <div class="flex items-start gap-3.5 sm:items-center">
          <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-white/20 bg-white/10 text-white shadow-xs">
            <Icon name="layers" :size="22" />
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-base font-extrabold tracking-wide text-white sm:text-lg">批量提取 · 打包下载</span>
            </div>
            <p class="mt-0.5 text-xs text-indigo-100 sm:text-sm">
              一次粘贴多条链接，后台自动逐条完成，无需逐个等待
            </p>
            <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-indigo-100">
              <span class="inline-flex items-center gap-1 font-semibold"><Icon name="check" :size="13" class="text-indigo-200" /> 自动去重</span>
              <span class="inline-flex items-center gap-1 font-semibold"><Icon name="check" :size="13" class="text-indigo-200" /> 后台自动执行</span>
              <span class="inline-flex items-center gap-1 font-semibold"><Icon name="check" :size="13" class="text-indigo-200" /> 一键打包导出</span>
            </div>
          </div>
        </div>

        <div class="shrink-0 self-stretch sm:self-center">
          <span class="inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-xl bg-white px-5 py-2.5 text-sm font-extrabold text-indigo-700 shadow-lg shadow-indigo-950/15 transition group-hover:bg-indigo-50 sm:w-auto">
            进入批量提取 <Icon name="arrow" :size="15" class="transition-transform group-hover:translate-x-0.5" />
          </span>
        </div>
      </RouterLink>

      <div class="mt-7 flex flex-wrap items-center justify-center gap-2">
        <span v-for="p in platforms" :key="p.name"
          class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-xs font-medium text-slate-600 backdrop-blur">
          <span class="h-2 w-2 rounded-full" :style="{ background: p.color }"></span>{{ p.name }}
        </span>
        <span class="text-xs text-slate-400">等 1800+ 站点</span>
      </div>
    </div>

    <!-- ResultCard (max-w-6xl = 1152px wide workspace) -->
    <div v-if="loading || info" id="result-panel" role="tabpanel" :aria-labelledby="`mode-tab-${activeView}`" class="relative mx-auto mt-6 max-w-6xl px-3 text-left sm:mt-8 sm:px-4 md:mt-12">
      <ResultCard
        :info="info"
        :loading="loading"
        :active-view="activeView"
        :auto-summarize-seq="autoSummarizeSeq"
        @update:active-view="selectTab($event)"
      />
    </div>
  </section>

  <!-- Stats -->
  <section class="border-y border-slate-200 bg-white">
    <div class="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-8 text-center sm:grid-cols-4 sm:px-6">
      <div v-for="s in [['1800+', '支持站点'], ['4K+', '原画画质'], ['免安装', '网页即用'], ['3 步', '完成下载']]" :key="s[1]">
        <div class="text-grad text-3xl font-extrabold sm:text-4xl">{{ s[0] }}</div>
        <div class="mt-1 text-sm text-slate-500">{{ s[1] }}</div>
      </div>
    </div>
  </section>

  <!-- Features -->
  <section class="bg-white py-16 sm:py-20">
    <div class="mx-auto max-w-6xl px-4 text-center sm:px-6">
      <h2 class="section-title">不止下载，<span class="text-grad">更省时间</span></h2>
      <p class="section-sub">平台不给下载、清晰度受限、不能批量？这些问题一个网址全部解决。</p>
      <div class="mt-10 grid gap-4 text-left sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="f in features" :key="f.title"
          class="group relative rounded-2xl border border-slate-200 bg-white p-6 transition hover:-translate-y-1 hover:border-indigo-200 hover:shadow-xl hover:shadow-indigo-500/10">
          <span class="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 transition group-hover:bg-gradient-to-br group-hover:from-blue-600 group-hover:via-indigo-500 group-hover:to-violet-600 group-hover:text-white">
            <Icon :name="f.icon" :size="22" />
          </span>
          <h3 class="mt-4 text-lg font-bold text-slate-900">{{ f.title }}</h3>
          <p class="mt-2 text-sm leading-relaxed text-slate-500">{{ f.desc }}</p>
        </div>
      </div>
    </div>
  </section>

  <!-- Steps -->
  <section id="steps" class="hero-bg py-16 sm:py-20">
    <div class="mx-auto max-w-6xl px-4 text-center sm:px-6">
      <h2 class="section-title">三步完成下载</h2>
      <p class="section-sub">全程网页操作，无需安装软件，手机电脑通用</p>
      <div class="mt-10 grid gap-4 text-left md:grid-cols-3">
        <div v-for="(s, i) in steps" :key="s.title" class="glass-card rounded-2xl p-6">
          <div class="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 via-indigo-500 to-violet-600 text-lg font-extrabold text-white">{{ i + 1 }}</div>
          <h3 class="mt-4 text-lg font-bold text-slate-900">{{ s.title }}</h3>
          <p class="mt-2 text-sm leading-relaxed text-slate-500">{{ s.desc }}</p>
        </div>
      </div>
    </div>
  </section>

  <!-- Platform table -->
  <section class="bg-white py-16 sm:py-20">
    <div class="mx-auto max-w-5xl px-4 text-center sm:px-6">
      <h2 class="section-title">平台功能支持一览</h2>
      <p class="section-sub">以下为常用平台，完整列表见 yt-dlp 支持站点（实际效果以平台接口为准）</p>
      <div class="mt-8 overflow-x-auto rounded-2xl border border-slate-200">
        <table class="w-full min-w-[560px] text-left text-sm">
          <thead class="bg-slate-50 text-xs uppercase text-slate-500">
            <tr><th class="px-4 py-3">平台</th><th class="px-4 py-3">视频</th><th class="px-4 py-3">MP3</th><th class="px-4 py-3">字幕</th><th class="px-4 py-3">说明</th></tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="p in platformTable" :key="p.name" class="hover:bg-indigo-50/40">
              <td class="px-4 py-3 font-semibold text-slate-900">{{ p.name }}</td>
              <td class="px-4 py-3 text-slate-700">{{ p.video }}</td>
              <td class="px-4 py-3"><Icon :name="p.audio ? 'check' : 'x'" :size="16" :class="p.audio ? 'text-emerald-500' : 'text-slate-300'" /></td>
              <td class="px-4 py-3"><Icon :name="p.sub ? 'check' : 'x'" :size="16" :class="p.sub ? 'text-emerald-500' : 'text-slate-300'" /></td>
              <td class="px-4 py-3 text-xs text-slate-500">{{ p.note }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- Scenarios -->
  <section class="bg-slate-50 py-16 sm:py-20">
    <div class="mx-auto max-w-6xl px-4 text-center sm:px-6">
      <h2 class="section-title">谁在用 FreeVideo？</h2>
      <div class="mt-10 grid gap-4 text-left sm:grid-cols-2 lg:grid-cols-4">
        <div v-for="(s, i) in scenarios" :key="s.who" class="rounded-2xl border border-slate-200 bg-white p-6">
          <div class="text-grad text-sm font-extrabold">0{{ i + 1 }}</div>
          <h3 class="mt-2 font-bold text-slate-900">{{ s.who }}</h3>
          <p class="mt-2 text-sm leading-relaxed text-slate-500">{{ s.text }}</p>
        </div>
      </div>
    </div>
  </section>

  <!-- FAQ -->
  <section id="faq" class="bg-white py-16 sm:py-20">
    <div class="mx-auto max-w-6xl px-4 sm:px-6">
      <h2 class="section-title text-center">常见问题</h2>
      <FaqList :items="faqs" class="mt-8" />
    </div>
  </section>

  <!-- CTA -->
  <section class="px-4 pb-16 sm:px-6">
    <div class="relative mx-auto max-w-5xl overflow-hidden rounded-3xl bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-600 px-6 py-12 text-center text-white shadow-2xl shadow-indigo-500/30 sm:py-16">
      <div class="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-white/10 blur-2xl"></div>
      <h2 class="text-2xl font-extrabold sm:text-4xl">登录即可免费使用，按需再升级</h2>
      <p class="mx-auto mt-3 max-w-xl text-sm text-indigo-100 sm:text-base">游客可免费下载 2 个视频；登录后下载不限次数，字幕提取、批量、AI 总结都能用，每月还有免费语音识别额度。需要更多时长与次数，可升级月卡或年卡。</p>
      <div class="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
        <RouterLink to="/pricing" class="btn-gold inline-flex items-center justify-center gap-2 rounded-xl px-8 py-3.5 font-bold">
          <Icon name="crown" :size="18" /> 查看会员与识别时长
        </RouterLink>
        <a href="#" class="inline-flex items-center justify-center rounded-xl border border-white/30 px-8 py-3.5 font-semibold text-white hover:bg-white/10" @click.prevent="scrollTop">继续免费使用</a>
      </div>
    </div>
  </section>
</template>
