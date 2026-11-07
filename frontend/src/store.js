import { reactive } from 'vue'

export const ui = reactive({
  upgradeOpen: false,
  upgradeReason: '',
  openUpgrade(reason = '') {
    this.upgradeReason = reason
    this.upgradeOpen = true
  },
})
