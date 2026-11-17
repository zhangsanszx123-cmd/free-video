<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import UserAvatar from '../components/UserAvatar.vue'
import FormField from '../components/FormField.vue'
import AdminDialog from './components/AdminDialog.vue'
import { adminAuth } from './adminAuth.js'
import { adminApi, passwordError } from './adminApi.js'
const route = useRoute()
const titles = { adminUsers: '注册用户', adminStaff: '后台账号', adminPricing: '会员价格', adminLimits: '套餐额度', adminHistory: '提取记录' }
const pageTitle = computed(() => titles[route.name] || '')
const editingPassword = ref(false), loggingOut = ref(false), menuOpen = ref(false)
watch(() => route.fullPath, () => { menuOpen.value = false })
const form = reactive({ old: '', next: '', busy: false, error: '' })
let disposed = false
const controller = new AbortController()
onUnmounted(() => { disposed = true; controller.abort() })
function openPassword() { Object.assign(form, { old: '', next: '', error: '' }); editingPassword.value = true }
async function changePassword() {
  if (form.busy) return
  form.error = !form.old ? '请输入当前密码' : passwordError(form.next, adminAuth.user?.username) || (form.old === form.next ? '新密码不能与当前密码相同' : '')
  if (form.error) return
  form.busy = true
  try {
    await adminApi.changePassword({ old_password: form.old, new_password: form.next }, controller.signal)
    if (!disposed) adminAuth.expire('后台密码已修改，所有后台设备已退出，请使用新密码登录')
  } catch (e) { if (!disposed && e.name !== 'AbortError') form.error = e.message }
  finally { form.busy = false }
}
async function logout() { if (loggingOut.value) return; loggingOut.value = true; try { await adminAuth.logout() } catch { /* local logout still completes */ } finally { loggingOut.value = false } }
</script>
<template>
  <div class="admin-bg h-dvh overflow-hidden">
    <button v-if="menuOpen" type="button" class="fixed inset-0 z-30 cursor-default bg-slate-950/50 backdrop-blur-sm lg:hidden" aria-label="关闭导航菜单" @click="menuOpen = false"></button>
    <aside id="admin-sidebar" class="admin-sidebar fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col px-4 py-5 transition-transform duration-300 lg:translate-x-0" :class="menuOpen ? 'translate-x-0' : 'max-lg:invisible max-lg:-translate-x-full'">
      <RouterLink to="/admin/users" class="flex items-center gap-3 px-2 text-white">
        <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/15"><img src="/logo.svg" alt="" class="h-6 w-6" /></span>
        <span class="leading-tight"><span class="block text-base font-extrabold tracking-tight">FreeVideo</span><span class="block text-xs font-medium text-indigo-200">管理后台</span></span>
      </RouterLink>
      <p class="mt-8 px-3 text-[11px] font-semibold tracking-widest text-indigo-300/70">功能菜单</p>
      <nav aria-label="后台管理导航" class="mt-2 flex flex-col gap-1.5">
        <RouterLink to="/admin/users" class="admin-nav-item" :class="{ 'admin-nav-item--active': route.name === 'adminUsers' }" :aria-current="route.name === 'adminUsers' ? 'page' : undefined"><Icon name="user" :size="18" />注册用户</RouterLink>
        <RouterLink v-if="adminAuth.isSuperadmin" to="/admin/staff" class="admin-nav-item" :class="{ 'admin-nav-item--active': route.name === 'adminStaff' }" :aria-current="route.name === 'adminStaff' ? 'page' : undefined"><Icon name="shield" :size="18" />后台账号</RouterLink>
        <RouterLink to="/admin/pricing" class="admin-nav-item" :class="{ 'admin-nav-item--active': route.name === 'adminPricing' }" :aria-current="route.name === 'adminPricing' ? 'page' : undefined"><Icon name="crown" :size="18" />会员价格</RouterLink>
        <RouterLink to="/admin/limits" class="admin-nav-item" :class="{ 'admin-nav-item--active': route.name === 'adminLimits' }" :aria-current="route.name === 'adminLimits' ? 'page' : undefined"><Icon name="clock" :size="18" />套餐额度</RouterLink>
        <RouterLink to="/admin/history" class="admin-nav-item" :class="{ 'admin-nav-item--active': route.name === 'adminHistory' }" :aria-current="route.name === 'adminHistory' ? 'page' : undefined"><Icon name="file" :size="18" />提取记录</RouterLink>
      </nav>
      <div class="mt-auto space-y-3">
        <RouterLink to="/" class="admin-nav-item"><Icon name="arrow" :size="16" />返回前台</RouterLink>
        <div class="flex items-center gap-3 rounded-2xl bg-white/10 p-3 ring-1 ring-white/10">
          <UserAvatar :name="adminAuth.user?.nickname || adminAuth.user?.username" :size="36" />
          <div class="min-w-0"><p class="truncate text-sm font-semibold text-white">{{ adminAuth.user?.nickname || adminAuth.user?.username }}</p><p class="mt-0.5 text-xs text-indigo-200">{{ adminAuth.isSuperadmin ? '超级管理员' : '普通管理员' }}</p></div>
        </div>
      </div>
    </aside>
    <div class="flex h-dvh min-h-0 flex-col lg:pl-[248px]">
      <header class="admin-topbar z-20 flex h-13 shrink-0 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <button type="button" class="flex h-10 w-10 items-center justify-center rounded-xl text-slate-600 hover:bg-slate-100 lg:hidden" aria-label="打开导航菜单" aria-controls="admin-sidebar" :aria-expanded="menuOpen" @click="menuOpen = true"><Icon name="menu" :size="22" /></button>
        <p class="hidden text-sm font-medium text-slate-500 lg:block">管理后台 <span class="mx-1.5 text-slate-300">/</span> <span class="font-semibold text-slate-800">{{ pageTitle }}</span></p>
        <div class="flex items-center gap-1.5 text-sm">
          <button class="flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-slate-600 hover:bg-indigo-50 hover:text-indigo-700" @click="openPassword"><Icon name="lock" :size="16" />修改密码</button>
          <button class="flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-slate-600 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50" :disabled="loggingOut" @click="logout"><Icon name="logout" :size="16" />{{ loggingOut ? '退出中…' : '退出' }}</button>
        </div>
      </header>
      <main class="admin-scroll min-h-0 min-w-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 lg:px-8 lg:py-4">
        <p v-if="adminAuth.notice" role="status" class="mb-4 flex items-center gap-2.5 rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-2.5 text-sm text-indigo-800 shadow-sm"><Icon name="alert" :size="18" class="shrink-0" /><span class="min-w-0 flex-1">{{ adminAuth.notice }}</span><button class="min-h-8 shrink-0 font-semibold" @click="adminAuth.notice = ''">关闭</button></p>
        <RouterView :key="`${String(route.name)}:${adminAuth.version}`" />
      </main>
    </div>
    <AdminDialog v-if="editingPassword" title="修改后台密码" :busy="form.busy" @close="editingPassword = false"><form class="space-y-4" @submit.prevent="changePassword"><input type="text" :value="adminAuth.user?.username" autocomplete="username" hidden /><FormField v-model="form.old" label="当前密码" type="password" autocomplete="current-password" :disabled="form.busy" autofocus /><FormField v-model="form.next" label="新密码" type="password" autocomplete="new-password" maxlength="128" hint="8–128 个字符，修改后所有后台设备将退出" :disabled="form.busy" /><p v-if="form.error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ form.error }}</p><button class="btn-primary min-h-12 w-full rounded-xl font-bold" :disabled="form.busy">{{ form.busy ? '保存中…' : '修改密码并退出' }}</button></form></AdminDialog>
  </div>
</template>
