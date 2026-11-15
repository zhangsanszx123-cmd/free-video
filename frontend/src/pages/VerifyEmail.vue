<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { account } from '../account.js'
import AuthShell from '../components/AuthShell.vue'

const route = useRoute()
const router = useRouter()
const token = ref('')
const busy = ref(false)
const done = ref(false)
const error = ref('验证链接缺少凭证，请打开完整邮件链接，或返回登录页重发。')
watch(() => route.hash, (hash) => {
  if (!hash) return
  token.value = new URLSearchParams(hash.slice(1)).get('token') || ''
  done.value = false
  error.value = token.value ? '' : '验证链接缺少凭证，请重新打开邮件链接。'
  // Clear the fragment through Vue Router too, so another link in this tab is handled correctly.
  router.replace({ path: route.path, query: route.query, hash: '' })
}, { immediate: true })
async function verify() {
  if (busy.value || done.value || !token.value) return
  busy.value = true
  error.value = ''
  try { await account.verifyEmail(token.value); done.value = true }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <AuthShell title="验证注册邮箱" subtitle="确认这是你本人发起的注册，再完成验证">
    <div class="mt-6 space-y-5">
      <p v-if="done" role="status" class="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-700">邮箱验证成功，注册已完成，你已自动登录。</p>
      <p v-else class="text-sm leading-6 text-slate-600">点击下方按钮将完成邮箱验证并登录对应账号。如果不是你本人注册，请关闭此页。</p>
      <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-600">{{ error }}</p>
      <button v-if="!done" :disabled="busy || !token" class="btn-primary min-h-12 w-full rounded-xl font-bold disabled:opacity-50" @click="verify">{{ busy ? '验证中…' : '确认验证并登录' }}</button>
      <RouterLink v-if="done" to="/" class="btn-primary flex min-h-12 items-center justify-center rounded-xl font-bold">开始使用</RouterLink>
      <RouterLink v-else to="/login" class="block py-3 text-center text-sm font-semibold text-indigo-600">返回登录页重发验证邮件</RouterLink>
    </div>
  </AuthShell>
</template>
