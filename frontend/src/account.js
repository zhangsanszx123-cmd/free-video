import { reactive } from 'vue'
import { ui } from './store.js'

const BATCH_SUBTITLES_KEY = 'fv-batch-subtitles'
const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('fv-auth') : null
const STORAGE_EVENT_KEY = 'fv-auth-event'
const LAST_USER_KEY = 'fv-auth-last-user'

async function call(path, { method = 'GET', body } = {}) {
  let res
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    })
  } catch {
    const error = new Error('网络连接失败，请检查网络后重试')
    error.status = 0
    throw error
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? '请求参数有误' : data.detail
    const error = new Error(detail || `请求失败（${res.status}）`)
    error.status = res.status
    error.code = data.code
    if (data.code === 'AUTH_REQUIRED') account.markLoggedOut('expired')
    throw error
  }
  return data
}

export const accountApi = {
  membership: () => call('/api/account/membership'),
  plans: () => call('/api/plans'),
  createOrder: (plan) => call('/api/pay/orders', { method: 'POST', body: { plan } }),
  order: (no) => call(`/api/pay/orders/${encodeURIComponent(no)}`),
  orders: () => call('/api/pay/orders'),
  history: (params) => call(`/api/account/history?${new URLSearchParams(params)}`),
  hideHistory: (id) => call(`/api/account/history/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  me: () => call('/api/auth/me'),
  register: (body) => call('/api/auth/register', { method: 'POST', body }),
  login: (body) => call('/api/auth/login', { method: 'POST', body }),
  logout: () => call('/api/auth/logout', { method: 'POST', body: {} }),
  updateProfile: (body) => call('/api/account/profile', { method: 'PATCH', body }),
  changePassword: (body) => call('/api/account/password', { method: 'POST', body }),
  sessions: () => call('/api/account/sessions'),
  revokeSession: (id) => call(`/api/account/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  revokeOthers: () => call('/api/account/sessions/revoke-others', { method: 'POST', body: {} }),
  deleteAccount: (body) => call('/api/account', { method: 'DELETE', body }),
}

/** Client-side mirrors of backend rules (account_auth.py); the server remains authoritative. */
export const rules = {
  username: (v) => (/^[A-Za-z0-9_]{4,32}$/.test(v) ? '' : '用户名需为 4–32 位字母、数字或下划线'),
  password(v, username = '') {
    const length = [...v].length // count code points like Python len()
    if (length < 8 || length > 128) return '密码长度需为 8–128 个字符'
    if (!v.trim()) return '密码不能全部为空白字符'
    if (username && v.toLowerCase() === username.toLowerCase()) return '密码不能与用户名相同'
    return ''
  },
  nickname(v) {
    const length = [...v.trim()].length
    if (length < 1 || length > 30) return '昵称长度需为 1–30 个字符'
    return /[\u0000-\u001f\u007f]/.test(v.trim()) ? '昵称不能包含控制字符' : ''
  },
}

/** Only same-site absolute paths are allowed as post-login destinations. */
export function safeRedirect(value, fallback = '/') {
  const target = Array.isArray(value) ? value[0] : value
  if (typeof target !== 'string' || !target.startsWith('/') || target.startsWith('//') || target.startsWith('/\\')) return fallback
  if (/^\/(login|register)(?:[/?#]|$)/.test(target)) return fallback
  return target
}

function announceGuestUsage(seconds) {
  if (seconds > 0) ui.notify(`游客期间下载的视频时长约 ${Math.ceil(seconds / 60)} 分钟，已计入本月语音识别额度`)
}

export const account = reactive({
  user: null,
  /** unknown: not checked yet · guest · authed · error: account service unreachable */
  status: 'unknown',
  error: '',
  /** Bumped when a logged-in identity ends or switches; App.vue keys RouterView on it to drop stale per-user UI. */
  version: 0,
  logoutReason: '',
  _pending: null,

  get loggedIn() { return this.status === 'authed' },

  /** Resolve the login state once (shared by router guard and components). */
  ensure() {
    if (this.status === 'guest' || this.status === 'authed') return Promise.resolve(this.user)
    return this.refresh()
  },

  refresh() {
    if (this._pending) return this._pending
    this._pending = accountApi.me()
      .then(({ user }) => { setUser(user, false); return user })
      .catch((e) => {
        this.status = 'error'
        this.error = e.message
        return null
      })
      .finally(() => { this._pending = null })
    return this._pending
  },

  async login(body) {
    const { user, guest_claimed_seconds: claimed } = await accountApi.login(body)
    setUser(user)
    announceGuestUsage(claimed)
    return user
  },

  async register(body) {
    const { user, guest_claimed_seconds: claimed } = await accountApi.register(body)
    setUser(user)
    announceGuestUsage(claimed)
    return user
  },

  async logout() {
    try { await accountApi.logout() } finally { this.markLoggedOut('logout') }
  },

  /**
   * Session ended. reason: 'logout' | 'password_changed' | 'deleted' | 'expired' (401 from a protected API).
   * App.vue reads it to decide where to go and whether to reopen the login dialog.
   */
  markLoggedOut(reason = '') {
    if (this.user) this.logoutReason = reason
    setUser(null)
  },

  updateUser(user) { setUser(user) },
})

/** Single login/register dialog (AuthModal.vue). Protected routes and login-only actions open it. */
export const authModal = reactive({ open: false, tab: 'login', notice: '', redirect: '', onSuccess: null })

/**
 * @param {{tab?: 'login'|'register', notice?: string, redirect?: string, onSuccess?: Function}} options
 * After success the dialog runs onSuccess, otherwise navigates to the (same-site) redirect, otherwise stays.
 */
export function openAuth({ tab = 'login', notice = '', redirect = '', onSuccess = null } = {}) {
  Object.assign(authModal, { open: true, tab, notice, redirect: redirect ? safeRedirect(redirect, '') : '', onSuccess })
}

export function closeAuth() {
  Object.assign(authModal, { open: false, notice: '', redirect: '', onSuccess: null })
}

/** Drop browser-local task references when the identity in this browser changes (not on reload). */
function syncPerUserState(userId) {
  try {
    const current = userId === null ? 'guest' : String(userId)
    const previous = localStorage.getItem(LAST_USER_KEY)
    if (previous !== null && previous !== current) localStorage.removeItem(BATCH_SUBTITLES_KEY)
    localStorage.setItem(LAST_USER_KEY, current)
  } catch { /* storage is optional */ }
}

function setUser(user, broadcast = true) {
  const before = account.user?.id ?? null
  const after = user?.id ?? null
  const initial = account.status === 'unknown'
  account.user = user || null
  account.status = user ? 'authed' : 'guest'
  account.error = ''
  syncPerUserState(after)
  // Remount pages only when a previous user's session ends or switches. Not on the first resolution after
  // page load, and not on guest -> login (so a pending action such as the home AI tab can resume in place).
  if (!initial && before !== null && before !== after) account.version += 1
  if (broadcast) notifyOtherTabs(after)
}

function notifyOtherTabs(userId) {
  const message = { type: 'auth-changed', userId, at: Date.now() }
  if (channel) channel.postMessage(message)
  else {
    try { localStorage.setItem(STORAGE_EVENT_KEY, JSON.stringify(message)) } catch { /* ignore */ }
  }
}

function onRemoteChange(message) {
  if (message?.type !== 'auth-changed') return
  account.refresh()
}

if (channel) channel.onmessage = (event) => onRemoteChange(event.data)
else if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_EVENT_KEY || !event.newValue) return
    try { onRemoteChange(JSON.parse(event.newValue)) } catch { /* ignore */ }
  })
}
