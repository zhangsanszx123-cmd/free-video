<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import UserAvatar from '../components/UserAvatar.vue'
import FormField from '../components/FormField.vue'
import AdminDialog from './components/AdminDialog.vue'
import { adminAuth } from './adminAuth.js'
import { adminApi, passwordError } from './adminApi.js'
const route = useRoute()
const editingPassword = ref(false), loggingOut = ref(false)
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
  <div class="min-h-screen bg-slate-50 text-slate-900">
    <header class="border-b border-slate-200 bg-white px-4 sm:px-6"><div class="mx-auto flex min-h-16 max-w-[1600px] flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2"><RouterLink to="/admin/users" class="flex items-center gap-2.5 font-extrabold"><img src="/logo.svg" alt="" class="h-8 w-8" /><span>Free<span class="text-grad">Video</span><span class="ml-2 text-sm font-medium text-slate-500">管理后台</span></span></RouterLink><div class="flex items-center gap-2 text-sm"><UserAvatar :name="adminAuth.user?.nickname || adminAuth.user?.username" :size="30" /><span class="max-w-32 truncate font-medium">{{ adminAuth.user?.nickname || adminAuth.user?.username }}</span><span class="hidden rounded-md bg-indigo-50 px-2 py-1 text-xs text-indigo-700 sm:inline">{{ adminAuth.isSuperadmin ? '超级管理员' : '普通管理员' }}</span><button class="min-h-11 rounded-lg px-2 font-medium text-slate-600 hover:bg-slate-100" @click="openPassword">修改密码</button><button class="min-h-11 rounded-lg px-2 font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50" :disabled="loggingOut" @click="logout">{{ loggingOut ? '退出中…' : '退出' }}</button></div></div></header>
    <div class="mx-auto grid max-w-[1600px] lg:grid-cols-[216px_minmax(0,1fr)]"><aside class="border-b border-slate-200 bg-white px-3 py-3 lg:min-h-[calc(100dvh-4rem)] lg:border-b-0 lg:border-r lg:px-4 lg:py-6"><nav aria-label="后台管理导航" class="flex flex-wrap gap-2 lg:flex-col"><RouterLink to="/admin/users" class="flex min-h-12 items-center gap-2 rounded-xl px-4 text-sm font-semibold" :class="route.name === 'adminUsers' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-50'" :aria-current="route.name === 'adminUsers' ? 'page' : undefined"><Icon name="user" :size="18" />注册用户</RouterLink><RouterLink v-if="adminAuth.isSuperadmin" to="/admin/staff" class="flex min-h-12 items-center gap-2 rounded-xl px-4 text-sm font-semibold" :class="route.name === 'adminStaff' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-50'" :aria-current="route.name === 'adminStaff' ? 'page' : undefined"><Icon name="shield" :size="18" />后台账号</RouterLink><RouterLink to="/admin/pricing" class="flex min-h-12 items-center gap-2 rounded-xl px-4 text-sm font-semibold" :class="route.name === 'adminPricing' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-50'" :aria-current="route.name === 'adminPricing' ? 'page' : undefined"><Icon name="crown" :size="18" />会员价格</RouterLink><RouterLink to="/admin/limits" class="flex min-h-12 items-center gap-2 rounded-xl px-4 text-sm font-semibold" :class="route.name === 'adminLimits' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-50'" :aria-current="route.name === 'adminLimits' ? 'page' : undefined"><Icon name="clock" :size="18" />套餐额度</RouterLink><RouterLink to="/admin/history" class="flex min-h-12 items-center gap-2 rounded-xl px-4 text-sm font-semibold" :class="route.name === 'adminHistory' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-50'" :aria-current="route.name === 'adminHistory' ? 'page' : undefined"><Icon name="file" :size="18" />提取记录</RouterLink></nav><RouterLink to="/" class="mt-8 hidden min-h-11 items-center gap-2 px-4 text-sm text-slate-500 hover:text-indigo-600 lg:flex"><Icon name="arrow" :size="16" />返回前台</RouterLink></aside><main class="min-w-0 px-4 py-6 sm:px-6 lg:p-8"><p v-if="adminAuth.notice" role="status" class="mb-5 rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-800">{{ adminAuth.notice }}<button class="ml-3 min-h-8 font-semibold" @click="adminAuth.notice = ''">关闭</button></p><RouterView :key="`${String(route.name)}:${adminAuth.version}`" /></main></div>
    <AdminDialog v-if="editingPassword" title="修改后台密码" :busy="form.busy" @close="editingPassword = false"><form class="space-y-4" @submit.prevent="changePassword"><input type="text" :value="adminAuth.user?.username" autocomplete="username" hidden /><FormField v-model="form.old" label="当前密码" type="password" autocomplete="current-password" :disabled="form.busy" autofocus /><FormField v-model="form.next" label="新密码" type="password" autocomplete="new-password" maxlength="128" hint="8–128 个字符，修改后所有后台设备将退出" :disabled="form.busy" /><p v-if="form.error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ form.error }}</p><button class="btn-primary min-h-12 w-full rounded-xl font-bold" :disabled="form.busy">{{ form.busy ? '保存中…' : '修改密码并退出' }}</button></form></AdminDialog>
  </div>
</template>
