import { reactive, watch } from 'vue'
import { account, accountApi } from './account.js'

export const membership = reactive({ data: null, loading: false, error: '' })
let generation = 0
let pending
watch(() => account.user?.id, () => {
  generation++
  pending = null
  Object.assign(membership, { data: null, loading: false, error: '' })
})

export function loadMembership() {
  if (!account.user) return Promise.resolve()
  if (pending) return pending
  const uid = account.user.id
  const current = generation
  membership.loading = true
  membership.error = ''
  pending = accountApi.membership().then(data => {
    if (current === generation && uid === account.user?.id) membership.data = data
  }).catch(error => {
    if (current === generation) membership.error = error.message
  }).finally(() => {
    if (current === generation) { membership.loading = false; pending = null }
  })
  return pending
}

export function durationLabel(seconds = 0) {
  const value = Math.max(0, Math.ceil(Number(seconds) || 0))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor(value % 3600 / 60)
  const rest = value % 60
  return [hours ? `${hours}小时` : '', minutes ? `${minutes}分钟` : '', rest ? `${rest}秒` : ''].join('') || '0分钟'
}
