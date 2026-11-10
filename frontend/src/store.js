import { reactive } from 'vue'

let toastTimer

export const ui = reactive({
  upgradeOpen: false,
  upgradeReason: '',
  toast: '',
  openUpgrade(reason = '') {
    this.upgradeReason = reason
    this.upgradeOpen = true
  },
  /** Short global status message (App.vue renders it). */
  notify(message, ms = 3000) {
    this.toast = message
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { this.toast = '' }, ms)
  },
})
