<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { accountApi } from '../account.js'
import { durationLabel, loadMembership } from '../membership.js'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const items = ref([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const appliedSearch = ref('')
const status = computed(() => ['active', 'done', 'error'].includes(route.query.status) ? route.query.status : 'all')
const loading = ref(false)
const error = ref('')
const opened = ref('')
const removing = ref('')
let version = 0
let disposed = false
let timer
const labels = { queued: '排队中', running: '执行中', done: '提取成功', error: '提取失败' }
const sources = { asr: '语音识别', platform_subtitle: '平台字幕', automatic_subtitle: '自动字幕' }
const fmtDate = value => new Date(value).toLocaleString('zh-CN', { hour12: false })

async function load() {
  const current = ++version
  clearTimeout(timer)
  loading.value = true
  error.value = ''
  try {
    const data = await accountApi.history({ page: page.value, status: status.value, search: appliedSearch.value })
    if (disposed || current !== version) return
    items.value = data.items
    total.value = data.total
    if (!items.value.length && page.value > 1 && total.value) { page.value--; return load() }
    if (status.value === 'active' || items.value.some(item => ['queued', 'running'].includes(item.status))) timer = setTimeout(load, 4000)
  } catch (e) {
    if (!disposed && current === version) error.value = e.message
  } finally {
    if (!disposed && current === version) loading.value = false
  }
}
function find() { page.value = 1; appliedSearch.value = search.value.trim(); load() }
async function remove(item) {
  if (removing.value) return
  removing.value = item.id
  try { await accountApi.hideHistory(item.id); await load() }
  catch (e) { error.value = e.message }
  finally { removing.value = '' }
}
function filter(event) { router.replace({ query: event.target.value === 'all' ? {} : { status: event.target.value } }) }
function paginate(value) { page.value = value; load() }
watch(status, () => { page.value = 1; opened.value = ''; load() })
onMounted(() => { load(); loadMembership() })
onUnmounted(() => { disposed = true; version++; clearTimeout(timer) })
</script>

<template>
  <section class="hero-bg min-h-[calc(100dvh-4rem)] px-4 py-8 sm:py-12">
    <div class="mx-auto max-w-5xl">
      <header class="flex flex-wrap items-center justify-between gap-4">
        <div><h1 class="flex items-center gap-3 text-2xl font-extrabold text-slate-950"><Icon :name="status === 'active' ? 'clock' : 'file'" class="text-indigo-600" />{{ status === 'active' ? '执行中任务' : '历史任务' }}</h1><p class="mt-2 text-sm leading-6 text-slate-600">任务记录与转录文本保存 30 天，同一账号可跨设备查看。</p></div>
        <RouterLink to="/account" class="btn-ghost flex min-h-11 items-center px-4 text-sm font-semibold">返回个人中心</RouterLink>
      </header>
      <form class="mt-6 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 sm:flex-row" @submit.prevent="find">
        <label class="min-w-0 flex-1"><span class="sr-only">搜索任务</span><input v-model="search" maxlength="100" placeholder="搜索视频标题或转录内容" class="input-control min-h-11 w-full rounded-xl px-4 text-sm" /></label>
        <button type="submit" class="btn-primary min-h-11 rounded-xl px-6 text-sm font-bold">搜索</button>
        <select aria-label="任务状态" :value="status" class="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm" @change="filter"><option value="all">全部状态</option><option value="active">执行中</option><option value="done">提取成功</option><option value="error">提取失败</option></select>
        <button type="button" :disabled="loading" class="btn-ghost min-h-11 rounded-xl px-4 text-sm font-semibold disabled:opacity-50" @click="load">刷新</button>
      </form>
      <p class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-900">历史文稿可直接复制和导出，不会再次扣时长。视频及音频文件仍为临时文件，重新下载需再次解析原链接。</p>
      <p v-if="error" role="alert" class="mt-4 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{{ error }}</p>
      <p v-if="loading && !items.length" role="status" class="py-16 text-center text-slate-500">正在加载任务…</p>
      <div v-else-if="!items.length && !error" class="mt-5 rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center"><Icon name="file" :size="36" class="mx-auto text-indigo-300" /><h2 class="mt-4 font-bold text-slate-800">暂无{{ status === 'active' ? '执行中的' : '匹配的' }}任务</h2><p class="mt-2 text-sm text-slate-500">提取平台字幕或使用语音识别后，记录会出现在这里。</p><RouterLink to="/" class="btn-primary mt-6 inline-flex min-h-11 items-center rounded-xl px-6 font-bold">去提取视频内容</RouterLink></div>
      <div v-else class="mt-5 space-y-4" :aria-busy="loading">
        <article v-for="item in items" :key="item.id" class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div class="flex items-start gap-4">
            <img v-if="item.thumbnail" :src="item.thumbnail" alt="" loading="lazy" referrerpolicy="no-referrer" class="hidden h-28 w-20 shrink-0 rounded-xl object-cover sm:block" @error="$event.target.style.display = 'none'" />
            <div class="min-w-0 flex-1">
              <h2 class="break-words font-bold leading-6 text-slate-900">{{ item.title }}</h2>
              <p class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs leading-6 text-slate-600"><span :class="item.status === 'error' ? 'text-rose-700' : item.status === 'done' ? 'text-emerald-700' : 'text-indigo-700'">{{ labels[item.status] }}</span><span>{{ item.platform }}</span><span>{{ fmtDate(item.created_at) }}</span><span v-if="item.duration_seconds">时长 {{ durationLabel(item.duration_seconds) }}</span><span>{{ sources[item.payload.result?.source] || item.payload.message }}</span></p>
              <p class="mt-1 text-xs leading-6 text-slate-600">{{ item.quota_state === 'settled' ? `已扣 ${durationLabel(item.quota_seconds)}` : ['reserved', 'unknown'].includes(item.quota_state) ? `预占 ${durationLabel(item.quota_seconds)}${item.quota_state === 'unknown' ? '（待核对）' : ''}` : '未扣除识别额度' }}</p>
              <p v-if="item.payload.error" class="mt-2 break-words text-sm leading-6 text-rose-700">{{ item.payload.error }}</p>
              <div class="mt-3 flex flex-wrap gap-2">
                <template v-if="item.status === 'done' && item.payload.result">
                  <button type="button" :aria-expanded="opened === item.id" class="btn-ghost min-h-11 px-3 text-sm font-semibold" @click="opened = opened === item.id ? '' : item.id">{{ opened === item.id ? '收起文稿' : '查看文稿' }}</button>
                  <a :href="`/api/account/history/${item.id}/file?format=txt`" class="btn-ghost flex min-h-11 items-center px-3 text-sm font-semibold">导出 TXT</a>
                  <a :href="`/api/account/history/${item.id}/file?format=srt`" class="btn-ghost flex min-h-11 items-center px-3 text-sm font-semibold">导出 SRT</a>
                </template>
                <RouterLink :to="{path:'/', query:{url:item.url}}" class="btn-ghost flex min-h-11 items-center px-3 text-sm font-semibold">重新打开视频</RouterLink>
                <button v-if="['done', 'error'].includes(item.status)" type="button" :disabled="Boolean(removing)" class="min-h-11 rounded-xl px-3 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50" @click="remove(item)">{{ removing === item.id ? '移除中…' : '移出历史' }}</button>
              </div>
            </div>
          </div>
          <div v-if="opened === item.id && item.payload.result" class="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4"><label :for="`text-${item.id}`" class="mb-2 block text-sm font-semibold text-slate-600">转录文稿（可选中复制）</label><textarea :id="`text-${item.id}`" readonly :value="item.payload.result.text" class="h-64 w-full resize-y bg-transparent text-sm leading-7 text-slate-800" /></div>
        </article>
      </div>
      <div v-if="total" class="mt-6 flex flex-wrap items-center justify-center gap-4 text-sm text-slate-600"><button type="button" :disabled="page <= 1 || loading" class="btn-ghost min-h-11 px-4 disabled:opacity-40" @click="paginate(page - 1)">上一页</button><span>第 {{ page }} / {{ Math.ceil(total / 20) }} 页 · {{ total }} 条</span><button type="button" :disabled="page * 20 >= total || loading" class="btn-ghost min-h-11 px-4 disabled:opacity-40" @click="paginate(page + 1)">下一页</button></div>
    </div>
  </section>
</template>
