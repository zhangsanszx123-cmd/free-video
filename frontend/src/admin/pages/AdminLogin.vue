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
<template><main class="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10"><div class="w-full max-w-[420px]"><div class="mb-7 flex items-center justify-center gap-3"><img src="/logo.svg" alt="" class="h-10 w-10" /><span class="text-xl font-extrabold">Free<span class="text-grad">Video</span><span class="ml-2 text-base font-medium text-slate-500">管理后台</span></span></div><section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8"><h1 class="text-2xl font-bold text-slate-950">后台登录</h1><p class="mt-2 text-sm leading-6 text-slate-500">使用已创建的后台账号登录</p><p v-if="adminAuth.notice || adminAuth.error" role="status" class="mt-5 rounded-xl bg-indigo-50 p-3 text-sm leading-6 text-indigo-800">{{ adminAuth.notice || adminAuth.error }}</p><form class="mt-6 space-y-4" @submit.prevent="login"><FormField v-model="username" label="后台登录名" autocomplete="username" maxlength="32" icon="user" :disabled="busy" autofocus /><FormField v-model="password" label="密码" type="password" autocomplete="current-password" maxlength="128" icon="lock" :disabled="busy" /><p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ error }}</p><button class="btn-primary flex min-h-12 w-full items-center justify-center gap-2 rounded-xl font-bold" :disabled="busy"><Icon v-if="busy" name="loader" class="animate-spin" :size="18" />{{ busy ? '登录中…' : '登录后台' }}</button></form><p class="mt-5 text-xs leading-6 text-slate-500">后台账号由超级管理员创建，与网站注册账号独立。</p></section><RouterLink to="/" class="mt-6 flex min-h-11 items-center justify-center text-sm text-slate-500 hover:text-indigo-600">返回前台网站</RouterLink></div></main></template>
