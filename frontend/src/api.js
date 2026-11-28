import { getAuthSessionVersion, handleAuthRequired } from './account.js'
import { streamLearnSSE } from './learning/learnApi.js'

async function request(path, options = {}) {
  const sessionVersion = getAuthSessionVersion()
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? '请求参数有误' : data.detail
    const error = new Error(detail || `请求失败（${res.status}）`)
    error.code = data.code
    error.retryable = data.retryable
    error.status = res.status
    if (data.code === 'AUTH_REQUIRED') handleAuthRequired(sessionVersion)
    throw error
  }
  return data
}

export const api = {
  guestAiStatus: (signal) => request('/api/guest/ai-summary', { signal, cache: 'no-store' }),
  guestAiSummary: (url, signal) => request('/api/guest/ai-summary', { method: 'POST', body: JSON.stringify({ url }), signal, cache: 'no-store' }),
  guestAiTask: (id, signal) => request(`/api/guest/ai-summary/${encodeURIComponent(id)}`, { signal, cache: 'no-store' }),
  health: (signal) => request('/api/health', { signal }),
  parse: (url, signal) => request('/api/parse', { method: 'POST', body: JSON.stringify({ url }), signal }),
  download: (body) => request('/api/download', { method: 'POST', body: JSON.stringify(body) }),
  batch: (body) => request('/api/batch', { method: 'POST', body: JSON.stringify(body) }),
  batchTranscribe: (urls, signal) => request('/api/batch-transcriptions', { method: 'POST', body: JSON.stringify({ urls, allow_asr: true }), signal }),
  batchTranscription: (id, signal) => request(`/api/batch-transcriptions/${id}`, { signal }),
  subtitles: (body) => request('/api/subtitles', { method: 'POST', body: JSON.stringify(body) }),
  transcript: (body, signal) => request('/api/transcript', { method: 'POST', body: JSON.stringify(body), signal }),
  transcriptionSession: () => request('/api/transcription-session'),
  transcribe: (body, signal) => request('/api/transcriptions', { method: 'POST', body: JSON.stringify(body), signal }),
  transcription: (id, signal) => request(`/api/transcriptions/${id}`, { signal }),
  translate: (body) => request('/api/ai/translate', { method: 'POST', body: JSON.stringify(body) }),
  job: (id) => request(`/api/jobs/${id}`),
}

export const fileUrl = (id) => `/api/jobs/${id}/file`
export const transcriptionFileUrl = (id, format) => `/api/transcriptions/${id}/file?format=${format}`

/** Poll a job until done/error. Returns a cancel function. */
export function pollJob(id, onUpdate, interval = 800) {
  let stopped = false
  const tick = async () => {
    if (stopped) return
    try {
      const job = await api.job(id)
      if (stopped) return
      onUpdate(job)
      if (job.status === 'done' || job.status === 'error') return
    } catch (e) {
      if (stopped) return
      if ([401, 403, 404].includes(e.status)) {
        onUpdate({ status: 'error', error: e.message })
        return
      }
      onUpdate({ message: '网络波动，正在恢复原任务查询…' })
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
  setTimeout(() => a.remove(), 1500)
}

/** Check JSON task metadata, then let the browser or download manager own the file transfer. */
export async function downloadArchive(href, filename, signal) {
  const sessionVersion = getAuthSessionVersion()
  const downloadUrl = new URL(href, window.location.href)
  const metadataUrl = new URL(downloadUrl)
  metadataUrl.pathname = metadataUrl.pathname.replace(/\/file$/, '')
  metadataUrl.search = ''
  const response = await fetch(metadataUrl, { signal, cache: 'no-store' })
  const task = await response.json().catch(() => ({}))
  if (task.code === 'AUTH_REQUIRED') handleAuthRequired(sessionVersion)
  if (!response.ok) throw new Error(task.detail || `\u4e0b\u8f7d\u5931\u8d25\uff08${response.status}\uff09\uff0c\u8bf7\u91cd\u8bd5`)
  const subtitleBatch = metadataUrl.pathname.startsWith('/api/batch-transcriptions/')
  if (!['done', 'error'].includes(task.status)) throw new Error('\u8bf7\u7b49\u5f85\u4efb\u52a1\u5b8c\u6210\u540e\u518d\u4e0b\u8f7d')
  if (subtitleBatch ? !task.succeeded : !task.ready) throw new Error('\u6587\u4ef6\u5c1a\u672a\u5c31\u7eea\u6216\u5df2\u8fc7\u671f')
  downloadUrl.searchParams.set('_download', `${Date.now()}-${Math.random().toString(36).slice(2)}`)
  triggerDownload(downloadUrl.href, filename)
}

/** POST + Server-Sent Events reader (EventSource only supports GET). */
export async function streamSSE(path, body, onEvent, signal) {
  return streamLearnSSE(path, body, onEvent, signal)
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
