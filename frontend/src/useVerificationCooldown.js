import { computed, onUnmounted, reactive, ref } from 'vue'

// Share cooldowns across the login/register forms, including reopening the dialog.
const deadlines = reactive(new Map())
const keyFor = (email) => email.trim().toLowerCase()

export function useVerificationCooldown(email, scope = 'verification') {
  const key = (value) => `${scope}:${keyFor(value)}`
  const now = ref(Date.now())
  const timer = setInterval(() => { now.value = Date.now() }, 250)
  onUnmounted(() => clearInterval(timer))
  const remaining = computed(() => Math.max(0, Math.ceil(((deadlines.get(key(email())) || 0) - now.value) / 1000)))
  function start(target, seconds = 60) {
    now.value = Date.now()
    deadlines.set(key(target), now.value + (Number.isFinite(seconds) && seconds > 0 ? seconds : 60) * 1000)
  }
  return { remaining, start }
}
