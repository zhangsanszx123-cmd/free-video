<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import FormField from '../components/FormField.vue'
import ForgotPasswordForm from '../components/ForgotPasswordForm.vue'
import { account, accountApi, rules } from '../account.js'

const route = useRoute()
const router = useRouter()
const resetting = computed(() => route.name === 'resetPassword')
const password = ref('')
const token = ref('')
const busy = ref(false)
const done = ref(false)
const error = ref('')
watch(() => route.hash, hash => {
  if (!hash || !resetting.value) return
  token.value = new URLSearchParams(hash.slice(1)).get('token') || ''
  password.value = ''
  done.value = false
  error.value = ''
  router.replace({ path: route.path, hash: '' })
}, { immediate: true })
async function submit() {
  if (busy.value || done.value || !token.value) return
  error.value = rules.password(password.value)
  if (error.value) return
  busy.value = true
  try {
    await accountApi.resetPassword(token.value, password.value)
    password.value = ''
    await account.refresh()
    done.value = true
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <AuthShell :title="resetting ? '设置新密码' : '找回密码'" :subtitle="resetting ? '设置完成后，请使用新密码重新登录' : '通过注册邮箱接收密码重置链接'">
    <ForgotPasswordForm v-if="!resetting" @login="router.push('/login')" />
    <form v-else class="mt-6 space-y-4" novalidate @submit.prevent="submit">
      <p v-if="done" role="status" class="rounded-xl bg-indigo-50 p-3 text-sm leading-6 text-indigo-700">密码已重置，所有登录设备已退出，请使用新密码登录。</p>
      <template v-if="!done">
        <p v-if="!token" role="alert" class="text-sm text-rose-600">重置链接缺少凭证，请重新打开邮件中的完整链接，或重新申请。</p>
        <FormField v-if="token" v-model="password" label="新密码" type="password" autocomplete="new-password" icon="lock" maxlength="128" placeholder="8–128 个字符" :disabled="busy" />
        <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-600">{{ error }}</p>
        <button type="submit" :disabled="busy || !token" class="btn-primary min-h-12 w-full rounded-xl font-bold disabled:opacity-50">{{ busy ? '处理中…' : '重置密码' }}</button>
      </template>
      <RouterLink v-if="resetting && !done" to="/forgot-password" class="block py-2 text-center text-sm font-semibold text-indigo-600">重新申请重置链接</RouterLink>
      <RouterLink to="/login" class="block py-2 text-center text-sm font-semibold text-indigo-600">返回登录</RouterLink>
    </form>
  </AuthShell>
</template>
