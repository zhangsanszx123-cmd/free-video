<script setup>
import { reactive, ref, watch } from 'vue'
import CaptchaField from './CaptchaField.vue'
import FormField from './FormField.vue'
import Icon from './Icon.vue'
import { account, accountApi, rules } from '../account.js'

const props = defineProps({ notice: { type: String, default: '' }, autofocus: { type: Boolean, default: false } })
const emit = defineEmits(['success', 'switch'])
const form = reactive({ email: '', password: '' })
const errors = reactive({ email: '', password: '' })
const captcha = ref(null)
const captchaAnswer = ref('')
const submitting = ref(false)
const error = ref('')
const pending = ref(false)
const sent = ref(false)
watch(() => form.email, () => { pending.value = false; sent.value = false })

function validate() {
  errors.email = rules.email(form.email.trim())
  errors.password = rules.password(form.password, form.email.trim())
  return !Object.values(errors).some(Boolean)
}

async function submit(resend = false) {
  if (submitting.value) return
  error.value = ''
  if (!validate()) return
  if (!resend && !captcha.value?.ready()) { error.value = '请输入图形验证码'; return }
  submitting.value = true
  try {
    const body = { email: form.email.trim(), password: form.password, ...(!resend ? captcha.value.payload() : {}) }
    const result = await (resend ? accountApi.resendVerification(body) : account.register(body))
    if (result.verification_required) { pending.value = true; sent.value = true }
    else emit('success', result)
  } catch (e) {
    if (['EMAIL_PENDING', 'EMAIL_SEND_FAILED'].includes(e.code)) pending.value = true
    if (e.status === 409) errors.email = e.message
    else error.value = e.message
  } finally {
    captcha.value?.refresh()
    submitting.value = false
  }
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
    <form class="mt-3 space-y-2.5" novalidate @submit.prevent="submit(pending)">
      <p v-if="sent" role="status" class="rounded-xl bg-indigo-50 p-3 text-sm text-indigo-700">验证邮件已发送，请前往邮箱点击链接完成注册。链接 30 分钟内有效；未收到请检查垃圾邮件，可在 60 秒后重发。</p>
      <FormField v-model="form.email" label="邮箱" type="email" icon="user" autocomplete="email" maxlength="254" :autofocus="props.autofocus"
        placeholder="请输入常用邮箱" :error="errors.email" />
      <FormField v-model="form.password" label="密码" type="password" icon="lock" autocomplete="new-password" maxlength="128"
        placeholder="设置密码（8–128 个字符）" :error="errors.password" />
      <CaptchaField v-if="!pending" ref="captcha" v-model="captchaAnswer" :disabled="submitting" />
      <p v-if="error" role="alert" class="flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
        <Icon name="alert" :size="16" class="shrink-0" /> {{ error }}
      </p>
      <button type="submit" :disabled="submitting" class="btn-primary flex min-h-12 w-full items-center justify-center gap-2 rounded-xl text-base font-bold">
        <Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
        {{ submitting ? '处理中…' : pending ? '重新发送验证邮件' : '注册账号' }}
      </button>
    </form>
    <p class="mt-3 text-center text-sm text-slate-500">
      已有账号？<button type="button" class="font-semibold text-indigo-600 hover:underline" @click="emit('switch')">直接登录</button>
    </p>
  </div>
</template>
