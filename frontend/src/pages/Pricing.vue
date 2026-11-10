<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import FaqList from '../components/FaqList.vue'
import { ui } from '../store.js'

const plans = [
  {
    name: '免费版', price: '0', unit: '永久', desc: '偶尔下载一两个视频',
    cta: '当前方案', features: ['每日 5 次下载', '最高 720P', 'MP3 音频提取', '字幕下载'], off: ['批量下载', 'AI 总结 / 翻译', '4K 原画'],
  },
  {
    name: 'Pro 月卡', price: '19.9', origin: '39.8', unit: '月', desc: '短期集中下载、追课程',
    cta: '开通月卡', features: ['无限次下载', '最高 4K / 8K 原画', '批量下载 20 条 + ZIP', 'AI 总结 30 次/月', '双语字幕翻译'], off: [],
  },
  {
    name: 'Pro 年卡', price: '99', origin: '238.8', unit: '年', desc: '学习、创作长期必备', hot: true, daily: '0.27',
    cta: '立即抢购年卡', features: ['包含月卡全部权益', 'AI 总结无限次', '多任务并行 · 专属高速通道', '新功能抢先体验', '7 天无理由退款'], off: [],
  },
]

const compare = [
  ['单次清晰度', '720P', '4K / 8K'],
  ['每日下载次数', '5 次', '无限'],
  ['批量下载 + ZIP', '—', '20 条/次'],
  ['AI 视频总结', '—', '✓'],
  ['AI 双语字幕', '—', '✓'],
  ['并行任务', '1', '3'],
]

const faqs = [
  { q: '可以先试用吗？', a: '可以。当前演示版所有 Pro 功能限时免费开放，批量提取与 AI 总结只需免费注册登录，你可以先完整体验再决定是否升级。' },
  { q: '支持哪些支付方式？', a: '计划支持微信支付、支付宝。当前为学习演示版本，在线支付尚未接入。' },
  { q: '不满意可以退款吗？', a: '年卡支持 7 天无理由退款（正式上线后生效）。' },
]

const left = ref('')
let timer
function tick() {
  const end = new Date()
  end.setHours(24, 0, 0, 0)
  const s = Math.max(0, Math.floor((end - Date.now()) / 1000))
  const pad = (n) => String(n).padStart(2, '0')
  left.value = `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`
}
onMounted(() => { tick(); timer = setInterval(tick, 1000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <section class="hero-bg py-12 sm:py-16">
    <div class="mx-auto max-w-6xl px-4 sm:px-6">
      <div class="text-center">
        <div class="inline-flex items-center gap-2 rounded-full bg-rose-50 px-3 py-1 text-xs font-bold text-rose-600 ring-1 ring-rose-200">
          <Icon name="clock" :size="14" /> 限时 5 折 · 距结束 <span class="font-mono tabular-nums">{{ left }}</span>
        </div>
        <h1 class="mt-4 text-3xl font-extrabold tracking-tight sm:text-5xl">选择适合你的 <span class="text-gold">Pro 方案</span></h1>
        <p class="mx-auto mt-4 max-w-2xl text-sm text-slate-600 sm:text-base">一次开通，全平台 4K 原画、批量打包、AI 总结与双语字幕全部解锁。</p>
      </div>

      <div class="mt-10 grid items-stretch gap-5 lg:grid-cols-3">
        <div v-for="p in plans" :key="p.name" class="relative flex flex-col rounded-3xl p-6 sm:p-8"
          :class="p.hot ? 'bg-slate-950 text-white shadow-2xl shadow-indigo-500/30 ring-2 ring-amber-400 lg:-my-3 lg:py-11' : 'glass-card'">
          <span v-if="p.hot" class="btn-gold absolute -top-3.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full px-4 py-1 text-xs font-extrabold">
            最受欢迎 · 立省 ¥139.8
          </span>
          <h3 class="text-lg font-bold" :class="p.hot ? 'text-amber-300' : 'text-slate-900'">{{ p.name }}</h3>
          <p class="mt-1 text-sm" :class="p.hot ? 'text-slate-400' : 'text-slate-500'">{{ p.desc }}</p>
          <div class="mt-5 flex items-end gap-2">
            <span class="text-lg font-bold">¥</span>
            <span class="text-5xl font-extrabold tracking-tight">{{ p.price }}</span>
            <span class="pb-1.5 text-sm" :class="p.hot ? 'text-slate-400' : 'text-slate-500'">/ {{ p.unit }}</span>
            <span v-if="p.origin" class="pb-1.5 text-sm line-through" :class="p.hot ? 'text-slate-500' : 'text-slate-400'">¥{{ p.origin }}</span>
          </div>
          <div v-if="p.daily" class="mt-2 text-sm font-semibold text-amber-300">折合每天仅 ¥{{ p.daily }}</div>
          <ul class="mt-6 flex-1 space-y-3 text-sm">
            <li v-for="f in p.features" :key="f" class="flex items-start gap-2">
              <Icon name="check" :size="16" class="mt-0.5 shrink-0" :class="p.hot ? 'text-amber-400' : 'text-emerald-500'" /> {{ f }}
            </li>
            <li v-for="f in p.off" :key="f" class="flex items-start gap-2 text-slate-400 line-through">
              <Icon name="x" :size="16" class="mt-0.5 shrink-0" /> {{ f }}
            </li>
          </ul>
          <button class="mt-8 w-full rounded-xl py-3.5 font-bold"
            :class="p.hot ? 'btn-gold' : p.price === '0' ? 'cursor-default border border-slate-200 bg-white text-slate-400' : 'btn-primary'"
            @click="p.price !== '0' && ui.openUpgrade('在线支付')">
            {{ p.cta }}
          </button>
        </div>
      </div>

      <div class="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-slate-500">
        <span class="flex items-center gap-1"><Icon name="shield" :size="14" class="text-emerald-500" /> 安全支付</span>
        <span class="flex items-center gap-1"><Icon name="check" :size="14" class="text-emerald-500" /> 7 天无理由退款</span>
        <span class="flex items-center gap-1"><Icon name="phone" :size="14" class="text-emerald-500" /> 手机电脑通用</span>
      </div>
    </div>
  </section>

  <section class="bg-white py-14">
    <div class="mx-auto max-w-3xl px-4 sm:px-6">
      <h2 class="section-title text-center">免费版 vs Pro</h2>
      <div class="mt-8 overflow-hidden rounded-2xl border border-slate-200">
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500">
            <tr><th class="px-4 py-3 text-left">权益</th><th class="px-4 py-3">免费版</th><th class="bg-amber-50 px-4 py-3 text-amber-700">Pro</th></tr>
          </thead>
          <tbody class="divide-y divide-slate-100 text-center">
            <tr v-for="r in compare" :key="r[0]">
              <td class="px-4 py-3 text-left font-medium text-slate-800">{{ r[0] }}</td>
              <td class="px-4 py-3 text-slate-500">{{ r[1] }}</td>
              <td class="bg-amber-50/40 px-4 py-3 font-bold text-amber-700">{{ r[2] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <h2 class="section-title mt-14 text-center">购买问题</h2>
      <FaqList :items="faqs" class="mt-8" />
    </div>
  </section>
</template>
