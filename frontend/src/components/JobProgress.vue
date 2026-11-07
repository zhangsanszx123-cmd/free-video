<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'
import { fileUrl, fmt, triggerDownload } from '../api.js'

const props = defineProps({ job: { type: Object, required: true } })
const statusText = computed(() => ({
  queued: '排队中…',
  running: props.job.message || '下载中…',
  processing: props.job.message || '处理中…',
  done: '已完成',
  error: '失败',
}[props.job.status] || props.job.status))
const pct = computed(() => Math.max(2, Math.min(100, props.job.progress || 0)))
const active = computed(() => ['queued', 'running', 'processing'].includes(props.job.status))
</script>

<template>
  <div class="rounded-2xl border border-slate-200 bg-white/90 p-4">
    <div class="flex items-center justify-between gap-3 text-sm">
      <div class="flex min-w-0 items-center gap-2 font-medium"
        :class="job.status === 'error' ? 'text-rose-600' : job.status === 'done' ? 'text-emerald-600' : 'text-slate-700'">
        <Icon v-if="active" name="loader" :size="16" class="shrink-0 animate-spin text-indigo-500" />
        <Icon v-else :name="job.status === 'done' ? 'check' : 'alert'" :size="16" class="shrink-0" />
        <span class="truncate">{{ job.status === 'error' ? job.error : statusText }}</span>
      </div>
      <div v-if="active" class="shrink-0 text-xs text-slate-500">
        <span v-if="job.speed">{{ fmt.size(job.speed) }}/s</span>
        <span v-if="job.eta" class="ml-2">剩余 {{ fmt.duration(job.eta) }}</span>
        <span class="ml-2 font-semibold text-indigo-600">{{ Math.round(job.progress || 0) }}%</span>
      </div>
    </div>
    <div v-if="job.status !== 'error'" class="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-100">
      <div class="h-full rounded-full bg-gradient-to-r from-blue-600 via-indigo-500 to-violet-500 transition-all duration-500"
        :class="{ 'progress-stripes': active }" :style="{ width: pct + '%' }"></div>
    </div>
    <button v-if="job.ready" class="btn-primary mt-4 flex w-full items-center justify-center gap-2 rounded-xl py-3 font-bold"
      @click="triggerDownload(fileUrl(job.id), job.filename)">
      <Icon name="download" :size="18" /> 保存到本地
      <span class="max-w-[50%] truncate text-xs font-normal opacity-80">{{ job.filename }}</span>
    </button>
    <slot />
  </div>
</template>
