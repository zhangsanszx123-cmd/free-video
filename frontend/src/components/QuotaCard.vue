<script setup>
import { computed, onMounted } from 'vue'
import { membership, loadMembership, durationLabel } from '../membership.js'
import Icon from './Icon.vue'
defineProps({ compact: Boolean })
const data = computed(() => membership.data)
const progress = computed(() => data.value?.limit_seconds ? Math.min(100, (data.value.used_seconds + data.value.reserved_seconds) / data.value.limit_seconds * 100) : 0)
const date = value => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : ''
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
      <div role="progressbar" aria-label="本月已使用及预占额度" :aria-valuenow="Math.round(progress)" aria-valuemin="0" aria-valuemax="100" class="mt-3 h-2 overflow-hidden rounded-full bg-indigo-100">
        <div class="h-full rounded-full bg-gradient-to-r from-blue-600 to-violet-600 transition-all" :style="{ width: `${progress}%` }"></div>
      </div>
      <p class="mt-2 text-xs leading-6 text-slate-600">已用 {{ durationLabel(data.used_seconds) }} · 处理中 {{ durationLabel(data.reserved_seconds) }}</p>
      <p v-if="data.pending_previous_seconds" class="text-xs leading-6 text-amber-800">往期待核对 {{ durationLabel(data.pending_previous_seconds) }}，暂占可用额度</p>
      <p v-if="!data.available_seconds" class="mt-2 text-sm font-semibold text-rose-700">本月可用额度已用完</p>
      <template v-if="!compact">
        <p class="mt-3 text-xs leading-6 text-slate-600">下次重置：{{ date(data.resets_at) }}（北京时间）</p>
        <p class="text-xs leading-6 text-slate-600">{{ data.expires_at ? `会员有效期至：${date(data.expires_at)}` : '免费用户每月赠送额度' }}</p>
        <p class="mt-3 text-sm leading-6 text-slate-600">仅语音识别扣时长。下载视频、提取平台字幕、复制和导出已有文稿不扣额度。任务及转录文本保存 30 天。</p>
      </template>
      <RouterLink to="/pricing" class="btn-primary mt-4 flex min-h-11 items-center justify-center rounded-xl px-4 text-sm font-bold">查看会员套餐</RouterLink>
    </template>
  </section>
</template>
