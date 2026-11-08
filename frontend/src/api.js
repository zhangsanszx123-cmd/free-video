async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? '请求参数有误' : data.detail
    throw new Error(detail || `请求失败（${res.status}）`)
  }
  return data
}

export const api = {
  health: () => request('/api/health'),
  parse: (url) => request('/api/parse', { method: 'POST', body: JSON.stringify({ url }) }),
  download: (body) => request('/api/download', { method: 'POST', body: JSON.stringify(body) }),
  batch: (body) => request('/api/batch', { method: 'POST', body: JSON.stringify(body) }),
  subtitles: (body) => request('/api/subtitles', { method: 'POST', body: JSON.stringify(body) }),
  transcript: (body) => request('/api/transcript', { method: 'POST', body: JSON.stringify(body) }),
  translate: (body) => request('/api/ai/translate', { method: 'POST', body: JSON.stringify(body) }),
  job: (id) => request(`/api/jobs/${id}`),
}

export const fileUrl = (id) => `/api/jobs/${id}/file`

/** Poll a job until done/error. Returns a cancel function. */
export function pollJob(id, onUpdate, interval = 800) {
  let stopped = false
  const tick = async () => {
    if (stopped) return
    try {
      const job = await api.job(id)
      onUpdate(job)
      if (job.status === 'done' || job.status === 'error') return
    } catch (e) {
      onUpdate({ status: 'error', error: e.message })
      return
    }
    setTimeout(tick, interval)
  }
  tick()
  return () => { stopped = true }
}

export function triggerDownload(href, filename = '') {
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/** POST + Server-Sent Events reader (EventSource only supports GET). */
export async function streamSSE(path, body, onEvent) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `请求失败（${res.status}）`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const event = raw.match(/^event: (.*)$/m)?.[1] || 'message'
      const data = raw.match(/^data: (.*)$/m)?.[1]
      onEvent(event, data ? JSON.parse(data) : null)
    }
  }
}

export const fmt = {
  size(bytes) {
    if (!bytes) return ''
    const units = ['B', 'KB', 'MB', 'GB']
    let i = 0
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
    return `${bytes.toFixed(i > 1 ? 1 : 0)}${units[i]}`
  },
  duration(sec) {
    if (!sec) return ''
    sec = Math.round(sec)
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60
    const pad = (n) => String(n).padStart(2, '0')
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
  },
  count(n) {
    if (!n) return ''
    return n >= 1e8 ? `${(n / 1e8).toFixed(1)}亿` : n >= 1e4 ? `${(n / 1e4).toFixed(1)}万` : String(n)
  },
}

export function extractUrls(text) {
  return [...new Set(text.match(/https?:\/\/[^\s<>"'，。！？、；）)】\]]+/g) || [])]
}
