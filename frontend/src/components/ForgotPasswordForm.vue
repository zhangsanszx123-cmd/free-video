<script setup>
import { ref, watch } from 'vue'
import FormField from './FormField.vue'
import { accountApi, rules } from '../account.js'
import { useVerificationCooldown } from '../useVerificationCooldown.js'
defineProps({ autofocus: Boolean })
const email = ref('')
const busy = ref(false)
const sent = ref(false)
const error = ref('')
const { remaining, start: startCooldown } = useVerificationCooldown(() => email.value, 'password-reset')
watch(email, () => { sent.value = false; error.value = '' })
async function submit() {
  if (busy.value || remaining.value > 0) return
  error.value = rules.email(email.value)
  if (error.value) return
  busy.value = true
  const targetEmail = email.value.trim()
  try {
    await accountApi.forgotPassword(targetEmail)
    sent.value = true
    startCooldown(targetEmail)
  }
  catch (e) {
    if (e.code === 'RATE_LIMIT' && e.message.includes('60 秒')) startCooldown(targetEmail)
    error.value = e.message
  }
  finally { busy.value = false }
}
</script>
<template>
  <form class="mt-5 space-y-4" novalidate @submit.prevent="submit">
    <p v-if="sent" role="status" class="rounded-xl bg-indigo-50 p-3 text-sm leading-6 text-indigo-700">如果该邮箱已注册，我们会发送重置邮件。请检查收件箱或垃圾邮件；链接 30 分钟有效，按钮倒计时结束后可重新申请。</p>
    <FormField v-model="email" label="注册邮箱" type="email" autocomplete="email" icon="user" maxlength="254" placeholder="请输入注册邮箱" :disabled="busy" :autofocus="autofocus" />
    <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-600">{{ error }}</p>
    <button type="submit" :disabled="busy || remaining > 0" class="btn-primary min-h-12 w-full rounded-xl font-bold disabled:opacity-50">{{ busy ? '发送中…' : remaining > 0 ? `${remaining} 秒后可重新发送` : sent ? '重新发送重置邮件' : '发送重置邮件' }}</button>
  </form>
</template>
