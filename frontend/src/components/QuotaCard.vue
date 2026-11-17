<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { membership, loadMembership, durationLabel } from '../membership.js'
import Icon from './Icon.vue'
defineProps({ compact: Boolean })
const data = computed(() => membership.data)
const progress = computed(() => data.value?.limit_seconds ? Math.max(0, Math.min(100, (1 - data.value.available_seconds / data.value.limit_seconds) * 100)) : 0)
const date = value => value ? new Date(value).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
}) : ''
let timer
function refreshVisible() { if (!document.hidden) loadMembership() }
onMounted(() => {
  loadMembership()
  timer = setInterval(refreshVisible, 30000)
  window.addEventListener('focus', refreshVisible)
  document.addEventListener('visibilitychange', refreshVisible)
})
onUnmounted(() => {
  clearInterval(timer)
  window.removeEventListener('focus', refreshVisible)
  document.removeEventListener('visibilitychange', refreshVisible)
})
</script>

<template>
  <section aria-label="语音识别额度" class="rounded-2xl border" :class="compact ? 'border-indigo-100 bg-indigo-50/60 p-3' : 'border-slate-200/80 bg-white p-5 shadow-sm sm:p-7'">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2 font-bold text-slate-900"><Icon name="crown" :size="18" class="text-indigo-600" />{{ data?.name || '我的会员额度' }}</div>
      <button type="button" class="min-h-11 rounded-lg px-2 text-sm font-semibold text-indigo-600 disabled:opacity-50" :disabled="membership.loading" @click="loadMembership">{{ membership.loading ? '加载中…' : '刷新额度' }}</button>
    </div>
    <p v-if="membership.error" role="alert" class="mt-2 text-sm text-rose-700">{{ membership.error }}</p>
    <template v-if="data">
      <div :class="compact ? '' : 'mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 sm:p-5'">
      <p class="mt-2 text-sm text-slate-600">视频转文字 · 每月 {{ durationLabel(data.limit_seconds) }}</p>
      <p class="mt-3 font-extrabold tracking-tight text-indigo-700" :class="compact ? 'text-lg' : 'text-2xl sm:text-3xl'">剩余 {{ durationLabel(data.available_seconds) }}</p>
      <div role="progressbar" aria-label="本期已使用及预占额度" :aria-valuenow="Math.round(progress)" aria-valuemin="0" aria-valuemax="100" class="mt-3 h-2 overflow-hidden rounded-full bg-indigo-100">
        <div class="h-full rounded-full bg-gradient-to-r from-blue-600 to-violet-600 transition-all" :style="{ width: `${progress}%` }"></div>
      </div>
      <p class="mt-2 text-xs leading-6 text-slate-600">已用 {{ durationLabel(data.used_seconds) }} · 处理中 {{ durationLabel(data.reserved_seconds) }}</p>
      <p v-if="data.pending_previous_seconds" class="text-xs leading-6 text-amber-800">往期待核对 {{ durationLabel(data.pending_previous_seconds) }}，暂占可用额度</p>
      <p v-if="!data.available_seconds" class="mt-2 text-sm font-semibold text-rose-700">本期可用额度已用完</p>
      </div>
      <ul v-if="!compact && data.ai_limit !== undefined" aria-label="套餐使用上限" class="mt-4 grid gap-3 sm:grid-cols-2">
        <li class="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 sm:p-5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-semibold text-slate-800">AI 视频总结</span>
            <span class="rounded-md bg-white px-2 py-1 text-xs text-slate-500 ring-1 ring-slate-200">本期</span>
          </div>
          <p class="mt-4 text-sm text-slate-500">本期已用 <span class="text-2xl font-bold tabular-nums" :class="data.ai_used >= data.ai_limit ? 'text-rose-600' : 'text-slate-900'">{{ data.ai_used }}</span><span class="ml-1 text-slate-500"> / {{ data.ai_limit }} 个视频</span></p>
          <p class="mt-2 text-xs leading-5" :class="data.ai_used >= data.ai_limit ? 'text-rose-600' : 'text-slate-500'">{{ data.ai_used >= data.ai_limit ? '本期次数已用完' : '同一视频多次使用，计为 1 个视频' }}</p>
        </li>
        <li class="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 sm:p-5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-semibold text-slate-800">AI 追问</span>
            <span class="rounded-md bg-white px-2 py-1 text-xs text-slate-500 ring-1 ring-slate-200">今日</span>
          </div>
          <p class="mt-4 text-sm text-slate-500">今日已用 <span class="text-2xl font-bold tabular-nums" :class="data.chat_used_today >= data.chat_daily_limit ? 'text-rose-600' : 'text-slate-900'">{{ data.chat_used_today }}</span><span class="ml-1 text-slate-500"> / {{ data.chat_daily_limit }} 条</span></p>
          <p class="mt-2 text-xs leading-5" :class="data.chat_used_today >= data.chat_daily_limit ? 'text-rose-600' : 'text-slate-500'">{{ data.chat_used_today >= data.chat_daily_limit ? '今日次数已用完' : '每天 00:00 重置（北京时间）' }}</p>
        </li>
        <li class="flex flex-wrap gap-x-8 gap-y-3 rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-600 sm:col-span-2">
          <p>批量提取 <span class="ml-2 font-semibold text-slate-900">单次最多 {{ data.batch_max_links }} 条</span></p>
          <p>单条识别 <span class="ml-2 font-semibold text-slate-900">最长 {{ data.asr_max_minutes }} 分钟</span></p>
        </li>
      </ul>
      <p class="mt-3 text-xs leading-6 text-slate-600">{{ data.ends_with_membership ? '会员到期' : '下次重置' }}：{{ date(data.resets_at) }}（北京时间）</p>
      <template v-if="!compact">
        <details class="mt-4 border-t border-slate-100 pt-4 text-sm text-slate-500">
          <summary class="w-fit cursor-pointer rounded-md font-medium text-slate-600 focus-visible:outline-2 focus-visible:outline-indigo-600">额度使用说明</summary>
          <p class="mt-2 max-w-2xl text-xs leading-6">仅语音识别扣时长；AI 次数按视频计（同一视频的总结、思维导图、追问共算 1 次，失败不扣）。下载视频、提取平台字幕、复制和导出已有文稿不扣额度。任务及转录文本保存 30 天。</p>
        </details>
      </template>
      <RouterLink to="/pricing" class="btn-primary mt-4 flex min-h-11 items-center justify-center rounded-xl px-6 text-sm font-bold" :class="compact ? '' : 'sm:inline-flex'">{{ data.payment_enabled ? (data.expires_at ? '续费 / 升级会员' : '开通会员') : '查看会员套餐' }}</RouterLink>
    </template>
  </section>
</template>
