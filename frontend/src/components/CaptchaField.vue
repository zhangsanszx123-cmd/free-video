<script setup>
import { onMounted, onBeforeUnmount, ref, useId } from 'vue'
import { accountApi } from '../account.js'
const answer = defineModel({ type: String, default: '' })
const props = defineProps({ disabled: Boolean })
const id = useId()
const challenge = ref(null)
const loading = ref(false)
const error = ref('')
let version = 0
async function refresh() {
  const current = ++version
  loading.value = true
  challenge.value = null
  answer.value = ''
  error.value = ''
  try {
    const result = await accountApi.captcha()
    if (current === version) challenge.value = result
  } catch (e) { if (current === version) error.value = e.message }
  finally { if (current === version) loading.value = false }
}
defineExpose({ refresh, payload: () => ({ captcha_id: challenge.value?.id || '', captcha_answer: answer.value }), ready: () => Boolean(challenge.value && answer.value.trim()) })
onMounted(refresh)
onBeforeUnmount(() => { version++ })
</script>
<template>
  <div>
    <label :for="id" class="mb-1.5 block text-sm font-semibold text-slate-700">图形验证码</label>
    <div class="flex items-center gap-2">
      <input :id="id" v-model="answer" type="text" inputmode="numeric" autocomplete="off" maxlength="2"
        placeholder="输入计算结果" :disabled="props.disabled || loading" :aria-invalid="Boolean(error)"
        :aria-describedby="error ? `${id}-error` : undefined"
        class="input-control min-h-12 min-w-0 flex-1 rounded-xl px-3 py-3 text-sm text-slate-900 placeholder-slate-400 disabled:opacity-60" />
      <button type="button" :disabled="loading || props.disabled" aria-label="刷新图形验证码" title="点击图片刷新验证码"
        class="flex h-12 w-32 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-indigo-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 disabled:cursor-wait sm:w-36" @click="refresh">
        <img v-if="challenge" :src="challenge.image" alt="算术验证码，请输入计算结果" width="176" height="56" class="h-full w-full object-contain" />
        <span v-else class="text-sm text-slate-500" role="status">{{ loading ? '加载中…' : '加载失败' }}</span>
      </button>
    </div>
    <p v-if="error" :id="`${id}-error`" role="alert" class="mt-2 text-sm text-rose-600">{{ error }}，请点击图片重试</p>
  </div>
</template>
