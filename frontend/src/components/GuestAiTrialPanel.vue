<script setup>
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import { renderLearningMarkdown } from '../learning/markdown.js'
import { platformTimeUrl } from '../learning/learnApi.js'
import { account } from '../account.js'
import '../learning/learning.css'

const props = defineProps({
  task: { type: Object, required: true },
  waiting: { type: Boolean, default: false },
  pollError: { type: String, default: '' },
})
const emit = defineEmits(['login', 'refresh', 'retry'])
const copied = ref('')
const html = computed(() => renderLearningMarkdown(props.task.summary || ''))
const active = computed(() => ['queued', 'running'].includes(props.task.status))
const title = computed(() => props.task.info?.title || '视频 AI 总结')
function safeUrl(value) {
  try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) ? u.href : '' }
  catch { return '' }
}
const sourceUrl = computed(() => safeUrl(props.task.info?.url || props.task.url))
const thumb = computed(() => safeUrl(props.task.info?.thumbnail))
const stateLabel = computed(() => ({ queued: '等待处理', running: '正在处理', done: '总结完成', error: props.task.summary ? '已保存部分总结' : '本次未完成', uncertain: '处理状态待核对' })[props.task.status] || '游客体验')
const canRetry = computed(() => props.task.status === 'error' && props.task.retryable && !['GUEST_AI_LIMIT', 'GUEST_AI_TOO_LONG', 'GUEST_AI_DURATION_UNKNOWN', 'GUEST_AI_TEXT_TOO_LONG'].includes(props.task.error_code))
async function copy() {
  try { await navigator.clipboard.writeText(props.task.summary || ''); copied.value = '总结已复制' }
  catch { copied.value = '无法自动复制，请选中正文手动复制' }
}
function seek(event) {
  const button = event.target.closest?.('[data-seek]')
  if (!button || !sourceUrl.value) return
  const seconds = Number(button.dataset.seek)
  if (Number.isFinite(seconds)) window.open(platformTimeUrl(sourceUrl.value, seconds), '_blank', 'noopener')
}
</script>

<template>
  <section class="glass-card rounded-3xl p-5 sm:p-7" aria-labelledby="guest-ai-title">
    <header class="flex flex-col gap-4 sm:flex-row sm:items-start">
      <img v-if="thumb" :src="thumb" alt="视频封面" class="aspect-video w-full rounded-xl object-cover sm:w-40" loading="lazy" />
      <div class="min-w-0 flex-1">
        <p class="text-xs font-bold tracking-wide text-indigo-600">游客 AI 总结体验 · 累计 1 个视频 · 最长 3 分钟</p>
        <h2 id="guest-ai-title" class="mt-2 break-words text-xl font-bold text-slate-950">{{ title }}</h2>
        <p class="mt-2 text-sm leading-6 text-slate-600">{{ stateLabel }}<span v-if="task.transcript?.source === 'asr'"> · 已使用语音转文字</span></p>
      </div>
      <a v-if="sourceUrl" :href="sourceUrl" target="_blank" rel="noopener" class="inline-flex min-h-11 items-center gap-1 self-start rounded-xl px-3 text-sm font-semibold text-indigo-700 hover:bg-indigo-50">打开原视频 <Icon name="arrow" :size="15" /></a>
    </header>

    <div v-if="active" role="status" class="mt-5 flex items-start gap-3 rounded-2xl bg-indigo-50 p-4 text-sm text-indigo-900">
      <Icon v-if="waiting" name="loader" :size="19" class="mt-0.5 shrink-0 animate-spin motion-reduce:animate-none" />
      <div><p class="font-semibold">{{ task.message || '正在准备视频文稿与总结…' }}</p><p class="mt-1 text-xs leading-6 text-indigo-800">后台处理不会因切换页面而取消。请查询原任务，不要重复提交。</p></div>
    </div>
    <div v-if="task.status === 'uncertain'" role="alert" class="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-950">{{ task.error || '本次处理状态暂时无法确认，体验名额已保留。请勿重复提交，可查询原任务或联系管理员。' }}</div>
    <p v-else-if="task.status === 'error'" role="alert" class="mt-5 rounded-xl bg-rose-50 p-4 text-sm leading-7 text-rose-800">{{ task.error || '本次总结未能完成，请查看提示后重试。' }}</p>
    <p v-if="pollError" role="alert" class="mt-4 rounded-xl bg-amber-50 p-4 text-sm leading-7 text-amber-950">{{ pollError }}</p>
    <div v-if="task.summary" class="mt-5 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6">
      <div class="mb-3 flex items-center justify-between gap-3"><h3 class="font-bold text-slate-900">视频总结</h3><button type="button" class="min-h-11 rounded-lg px-3 text-sm font-semibold text-indigo-700 hover:bg-indigo-50" @click="copy">复制总结</button></div>
      <div class="learn-prose break-words text-sm leading-8 text-slate-700" @click="seek" v-html="html"></div>
      <p v-if="copied" role="status" class="mt-3 text-xs leading-6 text-slate-600">{{ copied }}</p>
    </div>
    <div class="mt-5 flex flex-wrap gap-3">
      <button v-if="!account.loggedIn && ((active && !waiting) || task.status === 'uncertain' || pollError)" type="button" :disabled="waiting" class="btn-ghost inline-flex min-h-11 items-center rounded-xl px-4 text-sm font-semibold disabled:opacity-50" @click="emit('refresh')">查看处理状态</button>
      <button v-if="!account.loggedIn && canRetry" type="button" class="btn-ghost inline-flex min-h-11 items-center rounded-xl px-4 text-sm font-semibold" @click="emit('retry')">重试游客总结</button>
      <button v-if="!account.loggedIn" type="button" class="btn-primary inline-flex min-h-11 items-center rounded-xl px-5 text-sm font-semibold" @click="emit('login')">{{ task.summary ? '登录使用脑图与追问' : '登录账号' }}</button>
      <RouterLink v-else-if="sourceUrl" :to="{ path: '/learn', query: { url: sourceUrl } }" class="btn-primary inline-flex min-h-11 items-center rounded-xl px-5 text-sm font-semibold">进入 AI 学习工作台</RouterLink>
    </div>
    <p class="mt-4 text-xs leading-7 text-slate-500">这次体验包含无字幕视频的语音转写，与游客下载名额分开。登录后可继续总结更多视频、生成思维导图或追问；已生成的体验结果可继续查看。</p>
  </section>
</template>
