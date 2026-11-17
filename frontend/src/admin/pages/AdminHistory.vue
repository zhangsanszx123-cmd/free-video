<script setup>
import { ref } from 'vue'
import Icon from '../../components/Icon.vue'
import { fmt } from '../../api.js'
import AdminDialog from '../components/AdminDialog.vue'
import AdminPagination from '../components/AdminPagination.vue'
import { adminApi, adminDate } from '../adminApi.js'
import { useAdminList } from '../useAdminList.js'

const { items, total, loading, error, search, status, page, pages, apply, go, load } = useAdminList(adminApi.history, false, ['active', 'done', 'error'])
const detail = ref(null)
const labels = { queued: '排队中', running: '执行中', done: '提取成功', error: '提取失败' }
const sources = { asr: '语音识别', platform_subtitle: '平台字幕', automatic_subtitle: '自动字幕' }
const badge = value => value === 'done' ? 'bg-emerald-50 text-emerald-700' : value === 'error' ? 'bg-rose-50 text-rose-700' : 'bg-indigo-50 text-indigo-700'
function safeLink(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null }
  catch { return null }
}
</script>

<template>
  <section>
    <header class="admin-page-head flex-wrap"><span class="admin-page-icon"><Icon :size="20" name="file" /></span><div class="min-w-0"><h1 class="text-xl font-bold leading-tight tracking-tight text-slate-950">提取记录</h1><p class="mt-0.5 text-xs leading-5 text-slate-500 sm:text-sm">汇总所有用户的历史任务，与前台历史记录保持一致。</p></div><p class="w-full text-xs text-slate-500 lg:ml-auto lg:w-auto">仅展示现有历史表中未隐藏、未过期的字幕与转写任务；记录保存 30 天。</p></header>
    <form class="admin-card mt-3 flex flex-col gap-2.5 p-3 sm:flex-row sm:items-center" @submit.prevent="apply">
      <label class="min-w-0 flex-1"><span class="sr-only">搜索提取记录</span><input v-model="search" maxlength="100" placeholder="搜索视频标题或转录内容" class="input-control min-h-10 w-full rounded-xl px-4 text-sm" /></label>
      <select v-model="status" aria-label="任务状态" class="min-h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm" @change="apply"><option value="all">全部状态</option><option value="active">执行中</option><option value="done">提取成功</option><option value="error">提取失败</option></select>
      <button type="submit" class="btn-primary min-h-10 rounded-xl px-5 text-sm font-bold">搜索</button>
      <button type="button" :disabled="loading" class="min-h-10 rounded-xl border border-slate-200 px-4 text-sm font-semibold text-slate-600 disabled:opacity-50" @click="load">刷新</button>
    </form>
    <p v-if="error" role="alert" class="mt-3 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}<button type="button" class="ml-3 min-h-8 font-semibold underline" @click="load">重试</button></p>
    <div class="admin-card mt-3 overflow-hidden" :aria-busy="loading">
      <p v-if="loading" role="status" class="py-16 text-center text-sm text-slate-500">正在加载提取记录…</p>
      <div v-else-if="!items.length" class="px-5 py-16 text-center"><Icon name="file" :size="32" class="mx-auto text-slate-300" /><p class="mt-3 font-semibold text-slate-700">{{ error ? '暂时无法加载记录' : '暂无匹配的提取记录' }}</p></div>
      <template v-else>
        <div class="hidden overflow-x-auto md:block"><table class="admin-table w-full text-left text-sm"><thead class="border-b border-slate-200 bg-slate-50 text-xs text-slate-500"><tr><th class="px-5 py-2.5">视频</th><th class="px-4 py-2.5">用户邮箱</th><th class="px-4 py-2.5">来源</th><th class="px-4 py-2.5">状态</th><th class="px-4 py-2.5">提取时间（北京时间）</th><th class="px-5 py-2 text-right">操作</th></tr></thead><tbody class="divide-y divide-slate-100"><tr v-for="item in items" :key="item.id" class="hover:bg-slate-50/60"><td class="max-w-sm px-5 py-2"><p class="break-words font-semibold text-slate-900">{{ item.title }}</p><p class="mt-0.5 text-xs text-slate-500">{{ item.platform || '未知平台' }} · {{ fmt.duration(item.duration_seconds) || '时长未知' }}</p></td><td class="max-w-[240px] break-all px-4 py-1.5 text-slate-600">{{ item.user_email || '—' }}</td><td class="whitespace-nowrap px-4 py-1.5 text-slate-600">{{ sources[item.payload?.result?.source] || '—' }}</td><td class="whitespace-nowrap px-4 py-2"><span class="rounded-md px-2 py-1 text-xs font-semibold" :class="badge(item.status)">{{ labels[item.status] || item.status }}</span></td><td class="whitespace-nowrap px-4 py-1.5 text-xs text-slate-500">{{ adminDate(item.created_at) }}</td><td class="whitespace-nowrap px-5 py-1.5 text-right"><button class="min-h-8 rounded-lg px-3 font-semibold text-indigo-600 hover:bg-indigo-50" :aria-label="`查看 ${item.title} 记录`" @click="detail = item">查看</button></td></tr></tbody></table></div>
        <ul class="divide-y divide-slate-100 md:hidden"><li v-for="item in items" :key="item.id" class="p-4"><div class="flex items-start justify-between gap-3"><h2 class="min-w-0 break-words text-sm font-bold">{{ item.title }}</h2><span class="shrink-0 rounded-md px-2 py-1 text-xs font-semibold" :class="badge(item.status)">{{ labels[item.status] || item.status }}</span></div><p class="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500"><span class="break-all">用户邮箱 {{ item.user_email || '—' }}</span><span>{{ item.platform || '未知平台' }}</span><span>{{ sources[item.payload?.result?.source] || '来源待确定' }}</span></p><p class="mt-2 text-xs text-slate-500">{{ adminDate(item.created_at) }}</p><button class="mt-3 min-h-11 rounded-lg bg-indigo-50 px-4 text-sm font-semibold text-indigo-700" :aria-label="`查看 ${item.title} 记录`" @click="detail = item">查看记录</button></li></ul>
      </template>
    </div>
    <AdminPagination :page="page" :pages="pages" :total="total" :loading="loading" @change="go" />
    <AdminDialog v-if="detail" title="提取记录" wide @close="detail = null">
      <h2 class="break-words text-base font-bold text-slate-900">{{ detail.title }}</h2><p class="mt-2 break-all text-xs leading-6 text-slate-500">用户邮箱 {{ detail.user_email || '—' }} · {{ labels[detail.status] || detail.status }} · {{ adminDate(detail.created_at) }}</p>
      <a v-if="safeLink(detail.url)" :href="safeLink(detail.url)" target="_blank" rel="noopener noreferrer" class="mt-3 inline-flex min-h-11 items-center text-sm font-semibold text-indigo-600">打开原视频链接 <Icon name="arrow" :size="16" class="ml-1" /></a>
      <p v-if="detail.payload?.error" role="alert" class="mt-4 break-words rounded-xl bg-rose-50 p-4 text-sm leading-6 text-rose-700">{{ detail.payload.error }}</p>
      <pre v-if="detail.payload?.result?.text" class="mt-4 max-h-[50dvh] overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-slate-50 p-4 font-sans text-sm leading-7 text-slate-700">{{ detail.payload.result.text }}</pre>
      <p v-else class="mt-4 text-sm text-slate-500">暂无可展示的文稿。</p>
    </AdminDialog>
  </section>
</template>
