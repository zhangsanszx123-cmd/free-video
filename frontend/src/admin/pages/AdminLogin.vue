<script setup>
import { onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FormField from '../../components/FormField.vue'
import Icon from '../../components/Icon.vue'
import { adminAuth, safeAdminRedirect } from '../adminAuth.js'
const route = useRoute(), router = useRouter()
const username = ref(''), password = ref(''), busy = ref(false), error = ref('')
let disposed = false
onUnmounted(() => { disposed = true })
async function login() {
  if (busy.value) return
  error.value = !username.value.trim() || !password.value ? '请输入后台登录名和密码' : ''
  if (error.value) return
  busy.value = true
  try { await adminAuth.login({ username: username.value.trim(), password: password.value }); if (!disposed) router.replace(safeAdminRedirect(route.query.redirect)) }
  catch (e) { if (!disposed) error.value = e.message }
  finally { busy.value = false }
}
</script>
<template><main class="admin-bg grid min-h-screen lg:grid-cols-[1.05fr_1fr]"><aside class="admin-login-art hidden flex-col justify-between p-12 lg:flex"><div class="flex items-center gap-3"><span class="flex h-11 w-11 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/20"><img src="/logo.svg" alt="" class="h-7 w-7" /></span><span class="text-lg font-extrabold">FreeVideo</span></div><div><p class="text-sm font-semibold tracking-widest text-indigo-200">ADMIN CONSOLE</p><h2 class="mt-4 text-4xl font-extrabold leading-tight">统一管理<br />用户、会员与额度</h2><p class="mt-5 max-w-sm text-sm leading-7 text-indigo-100/90">查看注册用户、调整会员价格与套餐额度、核对提取记录，所有操作留有审计记录。</p></div><p class="text-xs text-indigo-200/80">仅限已授权的后台账号使用</p></aside><div class="flex items-center justify-center px-4 py-10"><div class="w-full max-w-[420px]"><div class="mb-7 flex items-center justify-center gap-3 lg:hidden"><img src="/logo.svg" alt="" class="h-10 w-10" /><span class="text-xl font-extrabold">Free<span class="text-grad">Video</span><span class="ml-2 text-base font-medium text-slate-500">管理后台</span></span></div><section class="admin-card p-6 sm:p-8"><h1 class="text-2xl font-bold text-slate-950">后台登录</h1><p class="mt-2 text-sm leading-6 text-slate-500">使用已创建的后台账号登录</p><p v-if="adminAuth.notice || adminAuth.error" role="status" class="mt-5 rounded-xl bg-indigo-50 p-3 text-sm leading-6 text-indigo-800">{{ adminAuth.notice || adminAuth.error }}</p><form class="mt-6 space-y-4" @submit.prevent="login"><FormField v-model="username" label="后台登录名" autocomplete="username" maxlength="32" icon="user" :disabled="busy" autofocus /><FormField v-model="password" label="密码" type="password" autocomplete="current-password" maxlength="128" icon="lock" :disabled="busy" /><p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ error }}</p><button class="btn-primary flex min-h-12 w-full items-center justify-center gap-2 rounded-xl font-bold" :disabled="busy"><Icon v-if="busy" name="loader" class="animate-spin" :size="18" />{{ busy ? '登录中…' : '登录后台' }}</button></form><p class="mt-5 text-xs leading-6 text-slate-500">后台账号由超级管理员创建，与网站注册账号独立。</p></section><RouterLink to="/" class="mt-6 flex min-h-11 items-center justify-center text-sm text-slate-500 hover:text-indigo-600">返回前台网站</RouterLink></div></div></main></template>
