<script setup>
import { ref } from 'vue'
import FormField from './FormField.vue'
import Icon from './Icon.vue'
import { account } from '../account.js'

const props = defineProps({ notice: { type: String, default: '' }, autofocus: { type: Boolean, default: false } })
const emit = defineEmits(['success', 'switch'])
const username = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')

async function submit() {
  if (submitting.value) return
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  submitting.value = true
  try {
    emit('success', await account.login({ username: username.value.trim(), password: password.value }))
  } catch (e) {
    error.value = e.message
  } finally {
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
    <form class="mt-5 space-y-4" novalidate @submit.prevent="submit">
      <FormField v-model="username" label="用户名" icon="user" autocomplete="username" maxlength="32" :autofocus="props.autofocus"
        placeholder="4–32 位字母、数字或下划线" />
      <FormField v-model="password" label="密码" type="password" icon="lock" autocomplete="current-password" maxlength="128" placeholder="请输入密码" />
      <p v-if="error" role="alert" class="flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
        <Icon name="alert" :size="16" class="shrink-0" /> {{ error }}
      </p>
      <button type="submit" :disabled="submitting" class="btn-primary flex min-h-12 w-full items-center justify-center gap-2 rounded-xl text-base font-bold">
        <Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
        {{ submitting ? '登录中…' : '登录' }}
      </button>
    </form>
    <p class="mt-5 text-center text-sm text-slate-500">
      还没有账号？<button type="button" class="font-semibold text-indigo-600 hover:underline" @click="emit('switch')">免费注册</button>
    </p>
  </div>
</template>
