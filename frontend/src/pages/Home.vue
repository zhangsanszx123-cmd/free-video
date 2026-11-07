<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import ResultCard from '../components/ResultCard.vue'
import FaqList from '../components/FaqList.vue'
import { api } from '../api.js'
import { faqs, features, platformTable, platforms, scenarios, steps } from '../data.js'

const modes = [
  { value: 'video', label: '视频 MP4', icon: 'video' },
  { value: 'audio', label: '音频 MP3', icon: 'music' },
  { value: 'subtitle', label: '字幕 SRT', icon: 'captions' },
]
const mode = ref('video')
const url = ref('')
const loading = ref(false)
const error = ref('')
const info = ref(null)

async function paste() {
  try {
    url.value = await navigator.clipboard.readText()
  } catch {
    error.value = '浏览器不允许读取剪贴板，请长按输入框手动粘贴'
  }
}

const scrollTop = () => window.scrollTo({ top: 0, behavior: 'smooth' })

const route = useRoute()
onMounted(() => {
  if (route.query.url) {
    url.value = String(route.query.url)
    if (['video', 'audio', 'subtitle'].includes(route.query.mode)) mode.value = route.query.mode
    parse()
  }
})

async function parse() {
  if (!url.value.trim() || loading.value) return
  loading.value = true
  error.value = ''
  info.value = null
  try {
    info.value = await api.parse(url.value.trim())
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <!-- Hero -->
  <section class="hero-bg relative overflow-hidden pb-14 pt-12 sm:pb-20 sm:pt-16 lg:pt-24">
    <div class="pointer-events-none absolute -left-24 top-24 h-72 w-72 rounded-full bg-blue-400/20 blur-3xl"></div>
    <div class="pointer-events-none absolute -right-24 top-10 h-72 w-72 rounded-full bg-violet-400/20 blur-3xl"></div>
    <div class="relative mx-auto max-w-5xl px-4 text-center sm:px-6">
      <div class="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50/90 px-3 py-1 text-xs font-semibold text-amber-700">
        <Icon name="gift" :size="14" /> 限时福利：Pro 会员 5 折<span class="hidden sm:inline">，4K + 批量 + AI 全解锁</span>
        <RouterLink to="/pricing" class="text-amber-800 underline-offset-2 hover:underline">查看 →</RouterLink>
      </div>
      <h1 class="mt-5 text-3xl font-extrabold leading-tight tracking-tight text-slate-950 sm:text-5xl lg:text-6xl">
        支持 1800+ 平台<br class="sm:hidden" />
        <span class="text-grad">高清视频一键下载</span>
      </h1>
      <p class="mx-auto mt-5 max-w-3xl text-sm leading-relaxed text-slate-600 sm:text-lg">
        粘贴链接，即可下载 B站、YouTube、TikTok、X、微博等平台的 <b class="text-slate-800">4K 原画视频</b>、
        <b class="text-slate-800">MP3 音频</b>与<b class="text-slate-800">字幕</b>；支持批量打包与 AI 视频总结。电脑、手机都能用。
      </p>

      <!-- Input shell -->
      <div class="input-shell mx-auto mt-8 max-w-4xl rounded-[1.75rem] p-3 text-left sm:p-5">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
          <div class="inline-flex rounded-xl bg-slate-100/90 p-1">
            <button v-for="m in modes" :key="m.value"
              class="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition sm:px-3 sm:text-sm"
              :class="mode === m.value ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'"
              @click="mode = m.value">
              <Icon :name="m.icon" :size="15" /> {{ m.label }}
            </button>
          </div>
          <div class="hidden items-center gap-1.5 text-xs text-slate-400 sm:flex">
            <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400"></span> 服务运行中 · 文件 30 分钟后自动删除
          </div>
        </div>
        <form class="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-2.5" @submit.prevent="parse">
          <div class="relative flex-1">
            <Icon name="link" :size="18" class="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
            <input v-model="url" type="text" inputmode="url" autocomplete="off"
              placeholder="粘贴视频链接或分享口令，如 https://b23.tv/xxxx"
              class="input-control w-full rounded-2xl py-4 pl-11 pr-24 text-sm text-slate-900 placeholder-slate-400 sm:text-base" />
            <div class="absolute right-2 top-1/2 flex -translate-y-1/2 gap-1">
              <button v-if="url" type="button" class="rounded-lg px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-100" @click="url = ''; info = null; error = ''">清空</button>
              <button v-else type="button" class="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50" @click="paste">
                <Icon name="clipboard" :size="14" /> 粘贴
              </button>
            </div>
          </div>
          <button type="submit" :disabled="loading || !url.trim()"
            class="btn-primary inline-flex min-h-[54px] items-center justify-center gap-2 rounded-2xl px-8 text-base font-bold">
            <Icon :name="loading ? 'loader' : 'zap'" :size="18" :class="{ 'animate-spin': loading }" />
            {{ loading ? '解析中…' : '立即解析' }}
          </button>
        </form>
        <p v-if="error" class="mt-3 flex items-start gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
          <Icon name="alert" :size="16" class="mt-0.5 shrink-0" /> {{ error }}
        </p>
        <div v-if="loading" class="mt-4 animate-pulse rounded-3xl border border-slate-100 bg-white/70 p-5">
          <div class="flex gap-4"><div class="aspect-video w-40 rounded-xl bg-slate-200"></div>
            <div class="flex-1 space-y-3"><div class="h-4 w-3/4 rounded bg-slate-200"></div><div class="h-3 w-1/2 rounded bg-slate-200"></div><div class="h-8 w-2/3 rounded bg-slate-200"></div></div></div>
        </div>
        <ResultCard v-if="info" :info="info" :mode="mode" class="mt-4" />
        <RouterLink v-if="!info" to="/batch"
          class="mt-3 flex items-center justify-between gap-3 rounded-2xl border border-indigo-100 bg-gradient-to-r from-blue-50 via-indigo-50 to-violet-50 px-4 py-3 transition hover:border-indigo-200 hover:shadow-md">
          <span class="flex items-center gap-3">
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 via-indigo-500 to-violet-600 text-white shadow-sm"><Icon name="layers" :size="18" /></span>
            <span>
              <span class="flex items-center gap-1.5 text-sm font-bold text-indigo-950">批量下载 <span class="pro-badge">PRO</span></span>
              <span class="block text-xs text-indigo-900/60">一次粘贴 20 条链接 · 自动去重 · 打包 ZIP</span>
            </span>
          </span>
          <Icon name="arrow" :size="18" class="text-indigo-400" />
        </RouterLink>
      </div>

      <div class="mt-7 flex flex-wrap items-center justify-center gap-2">
        <span v-for="p in platforms" :key="p.name"
          class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-xs font-medium text-slate-600 backdrop-blur">
          <span class="h-2 w-2 rounded-full" :style="{ background: p.color }"></span>{{ p.name }}
        </span>
        <span class="text-xs text-slate-400">等 1800+ 站点</span>
      </div>
    </div>
  </section>

  <!-- Stats -->
  <section class="border-y border-slate-200 bg-white">
    <div class="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-8 text-center sm:grid-cols-4 sm:px-6">
      <div v-for="s in [['1800+', '支持站点'], ['8K', '最高画质'], ['0', '广告与插件'], ['3 步', '完成下载']]" :key="s[1]">
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
          <span v-if="f.pro" class="pro-badge absolute right-4 top-4">PRO</span>
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
      <h2 class="text-2xl font-extrabold sm:text-4xl">每天不到一杯奶茶钱的 1/50</h2>
      <p class="mx-auto mt-3 max-w-xl text-sm text-indigo-100 sm:text-base">升级 Pro，解锁 4K 原画、批量下载、AI 总结与双语字幕，学习效率翻倍。</p>
      <div class="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
        <RouterLink to="/pricing" class="btn-gold inline-flex items-center justify-center gap-2 rounded-xl px-8 py-3.5 font-bold">
          <Icon name="crown" :size="18" /> 限时 5 折开通 Pro
        </RouterLink>
        <a href="#" class="inline-flex items-center justify-center rounded-xl border border-white/30 px-8 py-3.5 font-semibold text-white hover:bg-white/10" @click.prevent="scrollTop">继续免费使用</a>
      </div>
    </div>
  </section>
</template>
