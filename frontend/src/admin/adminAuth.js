import { reactive } from 'vue'

const CHANNEL = 'fv-admin-auth'
const STORAGE_KEY = 'fv-admin-auth-event'
const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel(CHANNEL) : null
let generation = 0
let sessionVersion = 0
let pending

export function safeAdminRedirect(value, fallback = '/admin/users') {
  const target = Array.isArray(value) ? value[0] : value
  if (typeof target !== 'string' || !/^\/admin(?:\/|$|\?)/.test(target) || target.includes('\\')
    || /^\/admin\/login(?:[/?#]|$)/.test(target)) return fallback
  return target
}

function announce(sessionChanged) {
  const event = { type: 'admin-changed', sessionChanged, at: Date.now() }
  if (channel) channel.postMessage(event)
  else { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(event)) } catch { /* optional */ } }
}

function setAdmin(admin, { broadcast = false, newSession = false } = {}) {
  generation++
  pending = null
  const changed = (adminAuth.user?.id ?? null) !== (admin?.id ?? null)
  const roleChanged = adminAuth.user?.role !== admin?.role
  if (changed || newSession) sessionVersion++
  if (changed || roleChanged) adminAuth.version++
  adminAuth.user = admin || null
  adminAuth.status = admin ? 'authed' : 'guest'
  adminAuth.error = ''
  if (broadcast) announce(changed || newSession)
}

export async function adminRequest(path, { method = 'GET', body, signal } = {}) {
  const current = sessionVersion
  let res
  try {
    res = await fetch(`/api/admin${path}`, {
      method, signal, cache: 'no-store',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('网络连接失败，请检查网络后重试')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const error = new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${res.status}）`)
    Object.assign(error, { code: data.code, status: res.status })
    if (current === sessionVersion && adminAuth.loggedIn && ['ADMIN_AUTH_REQUIRED', 'ADMIN_DISABLED'].includes(data.code)) {
      adminAuth.expire(data.code === 'ADMIN_DISABLED' ? '后台账号已停用，请联系超级管理员' : '后台登录已过期，请重新登录')
    } else if (current === sessionVersion && data.code === 'ADMIN_FORBIDDEN' && adminAuth.loggedIn) {
      adminAuth.refresh(true)
    }
    throw error
  }
  return data
}

export const adminAuth = reactive({
  user: null, status: 'unknown', error: '', notice: '', version: 0,
  get loggedIn() { return this.status === 'authed' },
  get isSuperadmin() { return this.loggedIn && this.user?.role === 'superadmin' },
  ensure() { return ['authed', 'guest'].includes(this.status) ? Promise.resolve(this.user) : this.refresh() },
  refresh(force = false) {
    if (force) { generation++; pending = null }
    if (pending) return pending
    const current = generation
    const task = adminRequest('/auth/me').then(({ admin }) => {
      if (current !== generation) return this.user
      setAdmin(admin)
      return admin
    }).catch(error => {
      if (current !== generation) return this.user
      this.status = 'error'
      this.error = error.message
      return null
    }).finally(() => { if (pending === task) pending = null })
    pending = task
    return task
  },
  async login(body) {
    const { admin } = await adminRequest('/auth/login', { method: 'POST', body })
    setAdmin(admin, { broadcast: true, newSession: true })
    this.notice = ''
    return admin
  },
  async logout() {
    const current = sessionVersion
    try { await adminRequest('/auth/logout', { method: 'POST', body: {} }) }
    finally { if (current === sessionVersion) this.expire('') }
  },
  expire(notice = '') {
    this.notice = notice
    setAdmin(null, { broadcast: true, newSession: true })
  },
  update(admin) { setAdmin(admin, { broadcast: true }) },
})

function remoteChange(message) {
  if (message?.type !== 'admin-changed') return
  if (message.sessionChanged !== false) sessionVersion++
  adminAuth.refresh(true)
}
if (channel) channel.onmessage = event => remoteChange(event.data)
else if (typeof window !== 'undefined') {
  window.addEventListener('storage', event => {
    if (event.key !== STORAGE_KEY || !event.newValue) return
    try { remoteChange(JSON.parse(event.newValue)) } catch { /* invalid event */ }
  })
}
