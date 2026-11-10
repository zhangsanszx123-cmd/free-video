<script setup>
import { reactive, ref } from 'vue'
import FormField from './FormField.vue'
import Icon from './Icon.vue'
import { account, rules } from '../account.js'

const props = defineProps({ notice: { type: String, default: '' }, autofocus: { type: Boolean, default: false } })
const emit = defineEmits(['success', 'switch'])
const form = reactive({ username: '', nickname: '', password: '', confirm: '' })
const errors = reactive({ username: '', nickname: '', password: '', confirm: '' })
const submitting = ref(false)
const error = ref('')

function validate() {
  errors.username = rules.username(form.username.trim())
  errors.nickname = form.nickname.trim() ? rules.nickname(form.nickname) : ''
  errors.password = rules.password(form.password, form.username.trim())
  errors.confirm = form.confirm === form.password ? '' : '两次输入的密码不一致'
  return !Object.values(errors).some(Boolean)
}

async function submit() {
  if (submitting.value) return
  error.value = ''
  if (!validate()) return
  submitting.value = true
  try {
    emit('success', await account.register({ username: form.username.trim(), password: form.password, nickname: form.nickname.trim() || null }))
  } catch (e) {
    if (e.status === 409) errors.username = e.message
    else error.value = e.message
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
      <FormField v-model="form.username" label="用户名" icon="user" autocomplete="username" maxlength="32" :autofocus="props.autofocus"
        placeholder="4–32 位字母、数字或下划线" hint="用于登录，不区分大小写，注册后不可修改" :error="errors.username" />
      <FormField v-model="form.nickname" label="昵称（可选）" icon="edit" autocomplete="nickname" maxlength="30"
        placeholder="默认与用户名相同" :error="errors.nickname" />
      <FormField v-model="form.password" label="密码" type="password" icon="lock" autocomplete="new-password" maxlength="128"
        placeholder="8–128 个字符" hint="建议混合字母、数字与符号" :error="errors.password" />
      <FormField v-model="form.confirm" label="确认密码" type="password" icon="lock" autocomplete="new-password" maxlength="128"
        placeholder="再次输入密码" :error="errors.confirm" />
      <p v-if="error" role="alert" class="flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
        <Icon name="alert" :size="16" class="shrink-0" /> {{ error }}
      </p>
      <button type="submit" :disabled="submitting" class="btn-primary flex min-h-12 w-full items-center justify-center gap-2 rounded-xl text-base font-bold">
        <Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
        {{ submitting ? '注册中…' : '注册并登录' }}
      </button>
    </form>
    <p class="mt-5 text-center text-sm text-slate-500">
      已有账号？<button type="button" class="font-semibold text-indigo-600 hover:underline" @click="emit('switch')">直接登录</button>
    </p>
  </div>
</template>
