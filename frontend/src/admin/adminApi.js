import { adminRequest } from './adminAuth.js'

export const adminApi = {
  users: (params, signal) => adminRequest(`/users?${new URLSearchParams(params)}`, { signal }),
  user: (id, signal) => adminRequest(`/users/${encodeURIComponent(id)}`, { signal }),
  userStatus: (id, body, signal) => adminRequest(`/users/${encodeURIComponent(id)}/status`, { method: 'PATCH', body, signal }),
  staff: (params, signal) => adminRequest(`/staff?${new URLSearchParams(params)}`, { signal }),
  createStaff: (body, signal) => adminRequest('/staff', { method: 'POST', body, signal }),
  updateStaff: (id, body, signal) => adminRequest(`/staff/${encodeURIComponent(id)}`, { method: 'PATCH', body, signal }),
  resetStaffPassword: (id, password, signal) => adminRequest(`/staff/${encodeURIComponent(id)}/password`, { method: 'POST', body: { password }, signal }),
  changePassword: (body, signal) => adminRequest('/auth/password', { method: 'POST', body, signal }),
}

export function passwordError(password, username = '') {
  if ([...password].length < 8 || [...password].length > 128) return '密码长度需为 8–128 个字符'
  if (!password.trim()) return '密码不能全部为空白字符'
  if (username && password.toLowerCase() === username.toLowerCase()) return '密码不能与登录名相同'
  return ''
}
export const adminDate = value => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'
