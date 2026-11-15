<script setup>
import { computed, onMounted } from 'vue'
import { membership, loadMembership, durationLabel } from '../membership.js'
import Icon from './Icon.vue'
defineProps({ compact: Boolean })
const data = computed(() => membership.data)
const progress = computed(() => data.value?.limit_seconds ? Math.max(0, Math.min(100, (1 - data.value.available_seconds / data.value.limit_seconds) * 100)) : 0)
const date = value => value ? new Date(value).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
}) : ''
onMounted(loadMembership)
</script>

<template>
  <section aria-label="语音识别额度" class="rounded-2xl border border-indigo-100 bg-indigo-50/60" :class="compact ? 'p-3' : 'p-5 sm:p-6'">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2 font-bold text-slate-900"><Icon name="crown" :size="18" class="text-indigo-600" />{{ data?.name || '我的会员额度' }}</div>
      <button type="button" class="min-h-11 rounded-lg px-2 text-sm font-semibold text-indigo-600 disabled:opacity-50" :disabled="membership.loading" @click="loadMembership">{{ membership.loading ? '加载中…' : '刷新额度' }}</button>
    </div>
    <p v-if="membership.error" role="alert" class="mt-2 text-sm text-rose-700">{{ membership.error }}</p>
    <template v-if="data">
      <p class="mt-2 text-sm text-slate-600">视频转文字 · 每月 {{ durationLabel(data.limit_seconds) }}</p>
      <p class="mt-3 text-lg font-extrabold text-indigo-700">剩余 {{ durationLabel(data.available_seconds) }}</p>
      <div role="progressbar" aria-label="本期已使用及预占额度" :aria-valuenow="Math.round(progress)" aria-valuemin="0" aria-valuemax="100" class="mt-3 h-2 overflow-hidden rounded-full bg-indigo-100">
        <div class="h-full rounded-full bg-gradient-to-r from-blue-600 to-violet-600 transition-all" :style="{ width: `${progress}%` }"></div>
      </div>
      <p class="mt-2 text-xs leading-6 text-slate-600">已用 {{ durationLabel(data.used_seconds) }} · 处理中 {{ durationLabel(data.reserved_seconds) }}</p>
      <p v-if="data.pending_previous_seconds" class="text-xs leading-6 text-amber-800">往期待核对 {{ durationLabel(data.pending_previous_seconds) }}，暂占可用额度</p>
      <p v-if="!data.available_seconds" class="mt-2 text-sm font-semibold text-rose-700">本期可用额度已用完</p>
      <ul v-if="data.ai_limit !== undefined" aria-label="套餐使用上限" class="mt-3 space-y-0.5 text-xs leading-6 text-slate-600">
        <li>AI 视频总结：本期已用 {{ data.ai_used }} / {{ data.ai_limit }} 个视频<span v-if="data.ai_used >= data.ai_limit" class="font-semibold text-rose-700">（已用完）</span></li>
        <li>AI 追问：今日已用 {{ data.chat_used_today }} / {{ data.chat_daily_limit }} 条</li>
        <li>批量提取：单次最多 {{ data.batch_max_links }} 条 · 单条识别最长 {{ data.asr_max_minutes }} 分钟</li>
      </ul>
      <p class="mt-3 text-xs leading-6 text-slate-600">{{ data.ends_with_membership ? '会员到期' : '下次重置' }}：{{ date(data.resets_at) }}（北京时间）</p>
      <template v-if="!compact">
        <p class="mt-3 text-sm leading-6 text-slate-600">仅语音识别扣时长；AI 次数按视频计（同一视频的总结、思维导图、追问共算 1 次，失败不扣）。下载视频、提取平台字幕、复制和导出已有文稿不扣额度。任务及转录文本保存 30 天。</p>
      </template>
      <RouterLink to="/pricing" class="btn-primary mt-4 flex min-h-11 items-center justify-center rounded-xl px-4 text-sm font-bold">{{ data.payment_enabled ? (data.expires_at ? '续费 / 升级会员' : '开通会员') : '查看会员套餐' }}</RouterLink>
    </template>
  </section>
</template>
