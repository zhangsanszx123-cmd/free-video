<script setup>
import { ref } from 'vue'
import FormField from './FormField.vue'
import { accountApi, rules } from '../account.js'
defineProps({ autofocus: Boolean })
const emit = defineEmits(['login'])
const email = ref('')
const busy = ref(false)
const sent = ref(false)
const error = ref('')
async function submit() {
  if (busy.value) return
  error.value = rules.email(email.value)
  if (error.value) return
  busy.value = true
  try { await accountApi.forgotPassword(email.value.trim()); sent.value = true }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <form class="mt-5 space-y-4" novalidate @submit.prevent="submit">
    <p v-if="sent" role="status" class="rounded-xl bg-indigo-50 p-3 text-sm leading-6 text-indigo-700">如果该邮箱已注册，我们会发送重置邮件。请检查收件箱或垃圾邮件；链接 30 分钟有效，60 秒后可重新申请。</p>
    <FormField v-model="email" label="注册邮箱" type="email" autocomplete="email" icon="user" maxlength="254" placeholder="请输入注册邮箱" :disabled="busy" :autofocus="autofocus" />
    <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-600">{{ error }}</p>
    <button type="submit" :disabled="busy" class="btn-primary min-h-12 w-full rounded-xl font-bold disabled:opacity-50">{{ busy ? '发送中…' : sent ? '重新发送重置邮件' : '发送重置邮件' }}</button>
    <button type="button" class="min-h-11 w-full text-sm font-semibold text-indigo-600" @click="emit('login')">返回登录</button>
  </form>
</template>
