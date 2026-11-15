<script setup>
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from './Icon.vue'
import LoginForm from './LoginForm.vue'
import RegisterForm from './RegisterForm.vue'
import { account, authModal, closeAuth } from '../account.js'

const router = useRouter()
const dialog = ref(null)
const tabs = [['login', '登录'], ['register', '注册']]
let previousOverflow = ''
let backdropPressed = false

function outsideDialog(event) {
  const bounds = dialog.value?.getBoundingClientRect()
  return bounds && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)
}

function onPointerDown(event) {
  backdropPressed = event.target === dialog.value && outsideDialog(event)
}

function onDialogClick(event) {
  const dismiss = backdropPressed && event.target === dialog.value && outsideDialog(event)
  backdropPressed = false
  if (dismiss) closeAuth()
}

function onDialogClose() {
  // Native close events are queued; an earlier close must not dismiss a newly opened dialog.
  if (!dialog.value?.open) closeAuth()
}

function trapFocus(event) {
  if (event.key !== 'Tab') return
  const controls = [...dialog.value.querySelectorAll('button, a[href], input, select, textarea, [tabindex="0"]')]
    .filter((el) => !el.disabled && el.getClientRects().length)
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(() => authModal.open, async (open) => {
  await nextTick()
  if (authModal.open !== open) return
  backdropPressed = false
  if (open) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    if (!dialog.value?.open) dialog.value?.showModal()
  } else {
    dialog.value?.close()
    document.body.style.overflow = previousOverflow
  }
}, { flush: 'post', immediate: true })
onUnmounted(() => { document.body.style.overflow = previousOverflow })

// Any login (this form, or another tab) completes the pending action once. The store update reaches this
// watcher before the form's `success` event, so onSuccess must be idempotent.
watch(() => account.loggedIn, (loggedIn) => { if (loggedIn) onSuccess() })

function onSuccess() {
  if (!authModal.open) return
  const { redirect, onSuccess: resume } = authModal
  closeAuth()
  if (resume) resume()
  else if (redirect) router.push(redirect)
}
</script>

<template>
  <dialog ref="dialog" aria-labelledby="auth-title"
    class="upgrade-dialog m-auto w-[calc(100%-2rem)] max-w-[420px] rounded-3xl bg-white p-0 shadow-2xl"
    @keydown="trapFocus" @close="onDialogClose" @cancel.prevent="closeAuth"
    @pointerdown="onPointerDown" @click="onDialogClick">
    <div v-if="authModal.open" class="p-6 sm:p-7">
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-2.5">
          <img src="/logo.svg" alt="" class="h-9 w-9" />
          <div>
            <h2 id="auth-title" class="text-xl font-extrabold tracking-tight text-slate-950">
              {{ authModal.tab === 'login' ? '欢迎回来' : '创建账号' }}
            </h2>
            <p class="text-xs text-slate-500">{{ authModal.tab === 'login' ? '登录后可提取字幕、语音识别、批量提取与 AI 总结' : '仅需用户名和密码，注册后自动登录' }}</p>
          </div>
        </div>
        <button type="button" class="-mr-2 -mt-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100" aria-label="关闭登录窗口" @click="closeAuth">
          <Icon name="x" />
        </button>
      </div>

      <div role="tablist" aria-label="登录或注册" class="mt-5 grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1">
        <button v-for="[key, label] in tabs" :key="key" type="button" role="tab" :aria-selected="authModal.tab === key"
          class="min-h-10 rounded-lg text-sm font-bold transition"
          :class="authModal.tab === key ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'"
          @click="authModal.tab = key">
          {{ label }}
        </button>
      </div>

      <LoginForm v-if="authModal.tab === 'login'" key="login" :notice="authModal.notice" autofocus
        @success="onSuccess" @switch="authModal.tab = 'register'" />
      <RegisterForm v-else key="register" :notice="authModal.notice" autofocus
        @success="onSuccess" @switch="authModal.tab = 'login'" />
    </div>
  </dialog>
</template>
