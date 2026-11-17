<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import Icon from '../../components/Icon.vue'
import UserAvatar from '../../components/UserAvatar.vue'
import AdminDialog from '../components/AdminDialog.vue'
import AdminPagination from '../components/AdminPagination.vue'
import AdminStatus from '../components/AdminStatus.vue'
import { adminApi, adminDate } from '../adminApi.js'
import { useAdminList } from '../useAdminList.js'

const { items, total, loading, error, search, status, verified, page, pages, apply, go, load } = useAdminList(adminApi.users, true)
const detailOpen = ref(false), detail = ref(null), detailLoading = ref(false), detailError = ref('')
const target = ref(null), notice = ref('')
const form = reactive({ reason: '', busy: false, error: '' })
let disposed = false, detailVersion = 0, detailController
const mutationController = new AbortController()
onUnmounted(() => { disposed = true; detailVersion++; detailController?.abort(); mutationController.abort() })
async function openDetail(user) {
  detailController?.abort()
  detailController = new AbortController()
  const current = ++detailVersion
  detailOpen.value = true; detailLoading.value = true; detailError.value = ''; detail.value = null
  try { const data = await adminApi.user(user.id, detailController.signal); if (!disposed && current === detailVersion) detail.value = data }
  catch (e) { if (!disposed && current === detailVersion && e.name !== 'AbortError') detailError.value = e.message }
  finally { if (!disposed && current === detailVersion) detailLoading.value = false }
}
function closeDetail() { detailOpen.value = false; detailVersion++; detailController?.abort() }
function openStatus(user) { target.value = user; Object.assign(form, { reason: '', busy: false, error: '' }) }
async function saveStatus() {
  if (form.busy || !target.value) return
  const user = target.value, nextStatus = user.status === 'active' ? 'disabled' : 'active'
  form.busy = true; form.error = ''
  try {
    await adminApi.userStatus(user.id, { status: nextStatus, ...(nextStatus === 'disabled' && form.reason.trim() ? { reason: form.reason.trim() } : {}) }, mutationController.signal)
    if (disposed) return
    target.value = null
    notice.value = `账号 ${user.email} 已${nextStatus === 'disabled' ? '禁用' : '启用'}`
    load()
  } catch (e) { if (!disposed && e.name !== 'AbortError') form.error = e.message }
  finally { form.busy = false }
}
</script>

<template>
  <section>
    <header class="admin-page-head"><span class="admin-page-icon"><Icon :size="20" name="user" /></span><div class="min-w-0"><h1 class="text-xl font-bold leading-tight tracking-tight text-slate-950">注册用户</h1><p class="mt-0.5 text-xs leading-5 text-slate-500 sm:text-sm">查询网站注册账号，管理账号启用状态。</p></div></header>
    <p v-if="notice" role="status" class="mt-3.5 rounded-xl bg-emerald-50 px-4 py-2.5 text-sm text-emerald-800">{{ notice }}</p>
    <form class="admin-card mt-3 flex flex-wrap items-center gap-2.5 p-3" @submit.prevent="apply">
      <label class="min-w-0 basis-full sm:flex-[1_1_200px]"><span class="sr-only">搜索注册用户</span><input v-model="search" maxlength="100" placeholder="邮箱、昵称或用户 ID" class="input-control min-h-10 w-full rounded-xl px-3 text-sm" /></label>
      <label class="min-w-[110px] flex-1 sm:flex-none"><span class="sr-only">账号状态</span><select aria-label="账号状态" v-model="status" class="min-h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm" @change="apply"><option value="all">全部状态</option><option value="active">已启用</option><option value="disabled">已禁用</option></select></label>
      <label class="min-w-[110px] flex-1 sm:flex-none"><span class="sr-only">邮箱验证</span><select aria-label="邮箱验证" v-model="verified" class="min-h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm" @change="apply"><option value="all">全部验证状态</option><option value="verified">已验证</option><option value="pending">待验证</option></select></label>
      <button class="btn-primary min-h-10 rounded-xl px-5 text-sm font-semibold">搜索</button><button type="button" :disabled="loading" class="btn-ghost min-h-10 px-4 text-sm font-semibold disabled:opacity-50" @click="load">刷新</button>
    </form>
    <p v-if="error" role="alert" class="mt-3.5 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}<button class="ml-3 min-h-8 font-semibold underline" @click="load">重试</button></p>
    <div class="admin-card mt-3 overflow-hidden" :aria-busy="loading">
      <div v-if="loading" role="status" class="space-y-3 p-5"><span class="sr-only">正在加载注册用户…</span><div v-for="n in 4" :key="n" class="admin-skeleton h-12 w-full"></div></div>
      <div v-else-if="!items.length" class="px-5 py-20 text-center"><span class="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-300"><Icon name="user" :size="30" /></span><p class="mt-3 font-semibold text-slate-700">{{ error ? '暂时无法加载用户' : '暂无匹配的注册用户' }}</p><p class="mt-2 text-sm text-slate-500">{{ error ? '请稍后重试。' : '可以调整搜索条件或筛选状态。' }}</p></div>
      <template v-else>
        <div class="hidden overflow-x-auto md:block"><table class="admin-table w-full text-left text-sm"><thead class="border-b border-slate-200 text-xs font-semibold text-slate-500"><tr><th class="px-5 py-2.5">用户</th><th class="px-4 py-2.5">邮箱验证</th><th class="px-4 py-2.5">状态</th><th class="px-4 py-2.5">会员</th><th class="px-4 py-2.5">注册时间（北京时间）</th><th class="px-5 py-2 text-right">操作</th></tr></thead><tbody class="divide-y divide-slate-100"><tr v-for="user in items" :key="user.id" class="hover:bg-slate-50/60"><td class="max-w-[300px] px-5 py-2"><div class="flex items-center gap-3"><UserAvatar :name="user.nickname || user.email" :size="32" class="shrink-0" /><div class="min-w-0"><div class="break-all font-semibold text-slate-900">{{ user.email }}</div><div class="mt-0.5 break-words text-xs text-slate-500">{{ user.nickname }} · ID {{ user.id }}</div></div></div></td><td class="whitespace-nowrap px-4 py-2"><span class="admin-badge" :class="user.email_verified ? 'admin-badge--ok' : 'admin-badge--warn'">{{ user.email_verified ? '已验证' : '待验证' }}</span></td><td class="whitespace-nowrap px-4 py-2"><AdminStatus :status="user.status" /></td><td class="whitespace-nowrap px-4 py-2"><span class="admin-badge" :class="user.membership ? 'admin-badge--gold' : 'admin-badge--muted'">{{ user.membership?.name || '免费用户' }}</span></td><td class="whitespace-nowrap px-4 py-1.5 text-xs text-slate-500">{{ adminDate(user.created_at) }}</td><td class="whitespace-nowrap px-5 py-1.5 text-right"><button class="min-h-8 rounded-lg px-3 font-semibold text-indigo-600 hover:bg-indigo-50" :aria-label="`查看 ${user.email} 详情`" @click="openDetail(user)">详情</button><button class="min-h-8 rounded-lg px-3 font-semibold hover:bg-slate-100" :class="user.status === 'active' ? 'text-rose-600' : 'text-emerald-700'" :aria-label="`${user.status === 'active' ? '禁用' : '启用'} ${user.email}`" @click="openStatus(user)">{{ user.status === 'active' ? '禁用' : '启用' }}</button></td></tr></tbody></table></div>
        <ul class="divide-y divide-slate-100 md:hidden"><li v-for="user in items" :key="user.id" class="p-4"><div class="flex items-start justify-between gap-3"><div class="min-w-0"><h2 class="break-all text-sm font-bold">{{ user.email }}</h2><p class="mt-1 break-words text-xs text-slate-500">{{ user.nickname }} · ID {{ user.id }}</p></div><AdminStatus :status="user.status" /></div><p class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500"><span>{{ user.email_verified ? '邮箱已验证' : '邮箱待验证' }}</span><span>{{ user.membership?.name || '免费用户' }}</span></p><p class="mt-2 text-xs text-slate-500">注册 {{ adminDate(user.created_at) }}</p><div class="mt-3 flex gap-2"><button class="btn-ghost min-h-11 px-4 text-sm font-semibold" :aria-label="`查看 ${user.email} 详情`" @click="openDetail(user)">详情</button><button class="min-h-11 rounded-xl px-4 text-sm font-semibold" :class="user.status === 'active' ? 'text-rose-600 hover:bg-rose-50' : 'text-emerald-700 hover:bg-emerald-50'" :aria-label="`${user.status === 'active' ? '禁用' : '启用'} ${user.email}`" @click="openStatus(user)">{{ user.status === 'active' ? '禁用' : '启用' }}</button></div></li></ul>
      </template>
    </div>
    <AdminPagination :page="page" :pages="pages" :total="total" :loading="loading" @change="go" />
    <AdminDialog v-if="detailOpen" title="注册用户详情" wide @close="closeDetail"><p v-if="detailLoading" role="status" class="py-10 text-center text-slate-500">正在加载详情…</p><p v-else-if="detailError" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ detailError }}</p><dl v-else-if="detail" class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-4 text-sm"><dt class="text-slate-500">用户 ID</dt><dd>{{ detail.id }}</dd><dt class="text-slate-500">邮箱</dt><dd class="break-all font-medium">{{ detail.email }}</dd><dt class="text-slate-500">昵称</dt><dd class="break-words">{{ detail.nickname }}</dd><dt class="text-slate-500">邮箱验证</dt><dd>{{ detail.email_verified ? '已验证' : '待验证' }}</dd><dt class="text-slate-500">账号状态</dt><dd><AdminStatus :status="detail.status" /></dd><dt class="text-slate-500">注册时间</dt><dd>{{ adminDate(detail.created_at) }}</dd><dt class="text-slate-500">当前会员</dt><dd>{{ detail.membership?.name || '免费用户' }}</dd><dt class="text-slate-500">会员到期</dt><dd>{{ adminDate(detail.membership?.expires_at) }}</dd><template v-if="detail.status === 'disabled'"><dt class="text-slate-500">禁用时间</dt><dd>{{ adminDate(detail.disabled_at) }}</dd><dt class="text-slate-500">禁用原因</dt><dd class="whitespace-pre-wrap break-words">{{ detail.disabled_reason || '未填写' }}</dd></template></dl></AdminDialog>
    <AdminDialog v-if="target" :title="target.status === 'active' ? '禁用注册用户' : '启用注册用户'" :busy="form.busy" @close="target = null"><form class="space-y-4" @submit.prevent="saveStatus"><p class="break-all text-sm font-semibold text-slate-900">{{ target.email }}</p><p class="text-sm leading-6 text-slate-600">{{ target.status === 'active' ? '禁用后，该用户将退出所有登录设备，不能登录或发起需要登录的新请求。已接受的任务继续处理，会员、用量、历史和订单保留。' : '启用后，该用户可重新登录。旧登录会话和邮件链接不会恢复，邮箱验证状态保持不变。' }}</p><label v-if="target.status === 'active'" class="block"><span class="mb-2 block text-sm font-medium text-slate-700">禁用原因（选填）</span><textarea v-model="form.reason" maxlength="500" rows="3" class="input-control w-full rounded-xl p-3 text-sm" :disabled="form.busy" /></label><p v-if="form.error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ form.error }}</p><button class="min-h-12 w-full rounded-xl font-bold text-white disabled:opacity-50" :class="target.status === 'active' ? 'bg-rose-600 hover:bg-rose-700' : 'btn-primary'" :disabled="form.busy">{{ form.busy ? '提交中…' : target.status === 'active' ? '确认禁用' : '确认启用' }}</button></form></AdminDialog>
  </section>
</template>
