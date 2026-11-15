<script setup>
import { ref } from 'vue'
import FormField from './FormField.vue'
import Icon from './Icon.vue'
import { account, accountApi, rules, authModal, openAuth } from '../account.js'

const props = defineProps({ notice: { type: String, default: '' }, autofocus: { type: Boolean, default: false } })
const emit = defineEmits(['success', 'switch'])
const email = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')
const needsVerification = ref(false)
const sent = ref(false)
function forgot() {
  if (authModal.open) authModal.tab = 'forgot'
  else openAuth({ tab: 'forgot' })
}

async function submit() {
  if (submitting.value) return
  error.value = ''
  if (!email.value.trim() || !password.value) {
    error.value = '请输入邮箱和密码'
    return
  }
  if (rules.email(email.value)) { error.value = rules.email(email.value); return }
  submitting.value = true
  try {
    emit('success', await account.login({ email: email.value.trim(), password: password.value }))
  } catch (e) {
    if (e.code === 'EMAIL_NOT_VERIFIED') needsVerification.value = true
    error.value = e.message
  } finally {
    submitting.value = false
  }
}

async function resend() {
  if (submitting.value) return
  if (rules.email(email.value) || !password.value) { error.value = '请填写邮箱和密码'; return }
  submitting.value = true
  error.value = ''
  try {
    await accountApi.resendVerification({ email: email.value.trim(), password: password.value })
    sent.value = true
  } catch (e) { error.value = e.message }
  finally { submitting.value = false }
}
</script>

<template>
  <div>
    <p v-if="account.status === 'error'" role="alert" class="mt-5 flex items-center justify-between gap-3 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-700">
      <span class="flex items-center gap-2"><Icon name="alert" :size="16" />{{ account.error || '账号服务暂不可用' }}</span>
      <button type="button" class="shrink-0 font-semibold underline-offset-2 hover:underline" @click="account.refresh()">重试</button>
    </p>
    <p v-else-if="props.notice" role="status" class="mt-5 flex items-center gap-2 rounded-xl bg-indigo-50 px-3 py-2.5 text-sm text-indigo-700">
      <Icon name="lock" :size="16" class="shrink-0" /> {{ props.notice }}
    </p>
    <form class="mt-5 space-y-4" novalidate @submit.prevent="submit">
      <p v-if="sent" role="status" class="rounded-xl bg-indigo-50 p-3 text-sm text-indigo-700">验证邮件已发送，请在 30 分钟内打开邮件链接。未收到请检查垃圾邮件，60 秒后可重发。</p>
      <FormField v-model="email" label="邮箱" type="email" icon="user" autocomplete="email" maxlength="254" :autofocus="props.autofocus"
        placeholder="请输入邮箱地址" />
      <FormField v-model="password" label="密码" type="password" icon="lock" autocomplete="current-password" maxlength="128" placeholder="请输入密码" />
      <div class="text-right"><button type="button" class="inline-flex min-h-11 items-center text-sm font-semibold text-indigo-600 hover:underline" @click="forgot">忘记密码？</button></div>
      <p v-if="error" role="alert" class="flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
        <Icon name="alert" :size="16" class="shrink-0" /> {{ error }}
      </p>
      <button type="submit" :disabled="submitting" class="btn-primary flex min-h-12 w-full items-center justify-center gap-2 rounded-xl text-base font-bold">
        <Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
        {{ submitting ? '登录中…' : '登录' }}
      </button>
      <button v-if="needsVerification" type="button" :disabled="submitting" class="min-h-11 w-full font-semibold text-indigo-600 disabled:opacity-50" @click="resend">重新发送验证邮件</button>
    </form>
    <p class="mt-5 text-center text-sm text-slate-500">
      还没有账号？<button type="button" class="font-semibold text-indigo-600 hover:underline" @click="emit('switch')">免费注册</button>
    </p>
  </div>
</template>
