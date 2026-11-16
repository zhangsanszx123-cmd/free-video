<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import Icon from '../../components/Icon.vue'
import FormField from '../../components/FormField.vue'
import AdminDialog from '../components/AdminDialog.vue'
import AdminPagination from '../components/AdminPagination.vue'
import AdminStatus from '../components/AdminStatus.vue'
import { adminAuth } from '../adminAuth.js'
import { adminApi, adminDate, passwordError } from '../adminApi.js'
import { useAdminList } from '../useAdminList.js'
const { items, total, loading, error, search, status, page, pages, apply, go, load } = useAdminList(adminApi.staff)
const editing = ref(false), target = ref(null), resetTarget = ref(null), notice = ref('')
const form = reactive({ username: '', nickname: '', password: '', role: 'admin', status: 'active', busy: false, error: '' })
const reset = reactive({ password: '', busy: false, error: '' })
let disposed = false
const controller = new AbortController()
onUnmounted(() => { disposed = true; controller.abort() })
function openEditor(staff = null) {
  target.value = staff
  Object.assign(form, { username: staff?.username || '', nickname: staff?.nickname || '', password: '', role: staff?.role || 'admin', status: staff?.status || 'active', busy: false, error: '' })
  editing.value = true
}
function validate() {
  const nickname = form.nickname.trim()
  if (!target.value && !/^[A-Za-z0-9_]{4,32}$/.test(form.username)) return '登录名需为 4–32 位字母、数字或下划线'
  if ([...nickname].length < 1 || [...nickname].length > 30 || /[\u0000-\u001f\u007f]/.test(nickname)) return '显示名称需为 1–30 个字符，不能包含控制字符'
  return target.value ? '' : passwordError(form.password, form.username)
}
async function save() {
  if (form.busy) return
  form.error = validate()
  if (form.error) return
  form.busy = true
  try {
    const { admin } = target.value
      ? await adminApi.updateStaff(target.value.id, { nickname: form.nickname.trim(), role: form.role, status: form.status }, controller.signal)
      : await adminApi.createStaff({ username: form.username, nickname: form.nickname.trim(), password: form.password, role: form.role }, controller.signal)
    if (disposed) return
    editing.value = false
    notice.value = target.value ? '后台账号已更新' : '后台账号已创建'
    form.password = ''
    if (admin.id === adminAuth.user?.id) adminAuth.update(admin)
    if (!disposed) load()
  } catch (e) { if (!disposed && e.name !== 'AbortError') form.error = e.message }
  finally { form.busy = false }
}
function openReset(staff) { resetTarget.value = staff; Object.assign(reset, { password: '', error: '', busy: false }) }
async function resetPassword() {
  if (reset.busy || !resetTarget.value) return
  reset.error = passwordError(reset.password, resetTarget.value.username)
  if (reset.error) return
  reset.busy = true
  const staff = resetTarget.value
  try {
    await adminApi.resetStaffPassword(staff.id, reset.password, controller.signal)
    if (disposed) return
    resetTarget.value = null; reset.password = ''
    if (staff.id === adminAuth.user?.id) adminAuth.expire('后台密码已重置，请使用新密码重新登录')
    else notice.value = `已重置 ${staff.username} 的密码，该账号所有后台设备已退出`
  } catch (e) { if (!disposed && e.name !== 'AbortError') reset.error = e.message }
  finally { reset.busy = false }
}
</script>
<template>
  <section>
    <header class="flex flex-wrap items-end justify-between gap-4"><div><p class="text-xs font-semibold tracking-wider text-indigo-600">权限管理</p><h1 class="mt-2 text-2xl font-bold tracking-tight text-slate-950">后台账号</h1><p class="mt-2 text-sm leading-6 text-slate-500">管理后台登录账号、角色与启用状态。</p></div><button class="btn-primary flex min-h-11 items-center gap-2 rounded-xl px-5 text-sm font-semibold" @click="openEditor()"><Icon name="user" :size="17" />新增后台账号</button></header>
    <p v-if="notice" role="status" class="mt-5 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{{ notice }}</p>
    <form class="mt-6 flex flex-wrap items-end gap-3 rounded-2xl border border-slate-200 bg-white p-4" @submit.prevent="apply"><label class="min-w-0 basis-full sm:flex-[1_1_240px]"><span class="mb-1.5 block text-sm font-medium text-slate-600">搜索后台账号</span><input v-model="search" maxlength="100" placeholder="登录名、显示名称或 ID" class="input-control min-h-11 w-full rounded-xl px-3 text-sm" /></label><label class="min-w-[120px] flex-1 sm:flex-none"><span class="mb-1.5 block text-sm font-medium text-slate-600">账号状态</span><select aria-label="账号状态" v-model="status" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm" @change="apply"><option value="all">全部状态</option><option value="active">已启用</option><option value="disabled">已禁用</option></select></label><button class="btn-primary min-h-11 rounded-xl px-5 text-sm font-semibold">搜索</button><button type="button" class="btn-ghost min-h-11 px-4 text-sm font-semibold disabled:opacity-50" :disabled="loading" @click="load">刷新</button></form>
    <p v-if="error" role="alert" class="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{{ error }}<button class="ml-3 min-h-8 font-semibold underline" @click="load">重试</button></p>
    <div class="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white" :aria-busy="loading"><p v-if="loading" role="status" class="py-20 text-center text-sm text-slate-500">正在加载后台账号…</p><div v-else-if="!items.length" class="px-5 py-20 text-center"><Icon name="shield" :size="32" class="mx-auto text-slate-300" /><p class="mt-3 font-semibold text-slate-700">{{ error ? '暂时无法加载后台账号' : '暂无匹配的后台账号' }}</p></div><template v-else>
      <div class="hidden overflow-x-auto md:block"><table class="w-full text-left text-sm"><thead class="border-b border-slate-200 bg-slate-50 text-xs font-semibold text-slate-500"><tr><th class="px-5 py-4">后台账号</th><th class="px-4 py-4">角色</th><th class="px-4 py-4">状态</th><th class="px-4 py-4">创建时间（北京时间）</th><th class="px-5 py-4 text-right">操作</th></tr></thead><tbody class="divide-y divide-slate-100"><tr v-for="staff in items" :key="staff.id" class="hover:bg-slate-50/60"><td class="px-5 py-4"><div class="break-words font-semibold text-slate-900">{{ staff.nickname }}<span v-if="staff.id === adminAuth.user?.id" class="ml-2 text-xs font-normal text-indigo-600">当前账号</span></div><p class="mt-1 text-xs text-slate-500">{{ staff.username }} · ID {{ staff.id }}</p></td><td class="whitespace-nowrap px-4 py-4"><span class="rounded-md px-2 py-1 text-xs font-semibold" :class="staff.role === 'superadmin' ? 'bg-indigo-50 text-indigo-700' : 'bg-slate-100 text-slate-600'">{{ staff.role === 'superadmin' ? '超级管理员' : '普通管理员' }}</span></td><td class="whitespace-nowrap px-4 py-4"><AdminStatus :status="staff.status" /></td><td class="whitespace-nowrap px-4 py-4 text-xs text-slate-500">{{ adminDate(staff.created_at) }}</td><td class="whitespace-nowrap px-5 py-3 text-right"><button class="min-h-11 rounded-lg px-3 font-semibold text-indigo-600 hover:bg-indigo-50" :aria-label="`编辑 ${staff.username}`" @click="openEditor(staff)">编辑</button><button class="min-h-11 rounded-lg px-3 font-semibold text-slate-600 hover:bg-slate-100" :aria-label="`重置 ${staff.username} 密码`" @click="openReset(staff)">重置密码</button></td></tr></tbody></table></div>
      <ul class="divide-y divide-slate-100 md:hidden"><li v-for="staff in items" :key="staff.id" class="p-4"><div class="flex items-start justify-between gap-3"><div class="min-w-0"><h2 class="break-words text-sm font-bold">{{ staff.nickname }}<span v-if="staff.id === adminAuth.user?.id" class="ml-2 text-xs font-normal text-indigo-600">当前账号</span></h2><p class="mt-1 text-xs text-slate-500">{{ staff.username }} · ID {{ staff.id }}</p></div><AdminStatus :status="staff.status" /></div><p class="mt-3 text-xs text-slate-500">{{ staff.role === 'superadmin' ? '超级管理员' : '普通管理员' }} · {{ adminDate(staff.created_at) }}</p><div class="mt-3 flex gap-2"><button class="btn-ghost min-h-11 px-4 text-sm font-semibold" :aria-label="`编辑 ${staff.username}`" @click="openEditor(staff)">编辑</button><button class="min-h-11 rounded-xl px-4 text-sm font-semibold text-slate-600 hover:bg-slate-100" :aria-label="`重置 ${staff.username} 密码`" @click="openReset(staff)">重置密码</button></div></li></ul>
    </template></div>
    <AdminPagination :page="page" :pages="pages" :total="total" :loading="loading" @change="go" />
    <AdminDialog v-if="editing" :title="target ? '编辑后台账号' : '新增后台账号'" :busy="form.busy" @close="editing = false; form.password = ''"><form class="space-y-4" @submit.prevent="save"><FormField v-model="form.username" label="后台登录名" autocomplete="off" maxlength="32" :disabled="Boolean(target) || form.busy" :hint="target ? '登录名创建后不可修改' : '4–32 位字母、数字或下划线'" /><FormField v-model="form.nickname" label="显示名称" maxlength="30" :disabled="form.busy" /><FormField v-if="!target" v-model="form.password" label="初始密码" type="password" autocomplete="new-password" maxlength="128" hint="8–128 个字符" :disabled="form.busy" /><label class="block"><span class="mb-1.5 block text-sm font-semibold text-slate-700">角色</span><select aria-label="角色" v-model="form.role" class="min-h-12 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm" :disabled="form.busy"><option value="admin">普通管理员</option><option value="superadmin">超级管理员</option></select><span class="mt-1 block text-xs leading-5 text-slate-500">普通管理员管理注册用户；超级管理员还可管理后台账号。</span></label><label v-if="target" class="block"><span class="mb-1.5 block text-sm font-semibold text-slate-700">账号状态</span><select aria-label="账号状态" v-model="form.status" class="min-h-12 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm disabled:bg-slate-50" :disabled="form.busy || target.id === adminAuth.user?.id"><option value="active">已启用</option><option value="disabled">已禁用</option></select><span v-if="target.id === adminAuth.user?.id" class="mt-1 block text-xs text-slate-500">不能禁用当前后台账号。</span></label><p v-if="target" class="text-xs leading-6 text-slate-500">至少保留一个启用的超级管理员；禁用后该账号的所有后台设备将退出。</p><p v-if="form.error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ form.error }}</p><button class="btn-primary min-h-12 w-full rounded-xl font-bold" :disabled="form.busy">{{ form.busy ? '保存中…' : target ? '保存修改' : '创建后台账号' }}</button></form></AdminDialog>
    <AdminDialog v-if="resetTarget" title="重置后台账号密码" :busy="reset.busy" @close="resetTarget = null; reset.password = ''"><form class="space-y-4" @submit.prevent="resetPassword"><p class="text-sm font-semibold">{{ resetTarget.username }}</p><p class="text-sm leading-6 text-slate-600">设置一个新密码。重置成功后，该账号的所有后台登录设备将退出。</p><FormField v-model="reset.password" label="新密码" type="password" autocomplete="new-password" maxlength="128" hint="8–128 个字符" :disabled="reset.busy" /><p v-if="reset.error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ reset.error }}</p><button class="btn-primary min-h-12 w-full rounded-xl font-bold" :disabled="reset.busy">{{ reset.busy ? '重置中…' : '确认重置密码' }}</button></form></AdminDialog>
  </section>
</template>
