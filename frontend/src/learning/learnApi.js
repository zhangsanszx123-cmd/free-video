/** Dedicated API & timestamp helpers for the AI video learning suite (/api/learn/*). */
import { account } from '../account.js'

export async function streamLearnSSE(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const detail = Array.isArray(data.detail) ? '请求参数有误' : data.detail
    const err = new Error(detail || `请求失败（${res.status}）`)
    err.code = data.code
    err.status = res.status
    if (data.code === 'AUTH_REQUIRED') account.markLoggedOut('expired')
    throw err
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatchBlock = (rawBlock) => {
    const lines = rawBlock.split(/\r?\n/)
    let eventName = 'message'
    const dataLines = []
    for (const line of lines) {
      if (!line || line.startsWith(':')) continue // ignore keep-alive comments
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim() || 'message'
      } else if (line.startsWith('data:')) {
        const val = line.slice(5)
        dataLines.push(val.startsWith(' ') ? val.slice(1) : val)
      }
    }
    if (!dataLines.length) return
    const joined = dataLines.join('\n')
    let parsed = joined
    try {
      parsed = JSON.parse(joined)
    } catch {
      /* keep raw string if non-JSON */
    }
    onEvent(eventName, parsed)
  }

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let match
    while ((match = /\r?\n\r?\n/.exec(buffer)) !== null) {
      const raw = buffer.slice(0, match.index)
      buffer = buffer.slice(match.index + match[0].length)
      if (raw.trim()) dispatchBlock(raw)
    }
  }
  if (buffer.trim()) dispatchBlock(buffer)
}

export const learnApi = {
  summary: (body, onEvent, signal) => streamLearnSSE('/api/learn/summary', body, onEvent, signal),
  chat: (body, onEvent, signal) => streamLearnSSE('/api/learn/chat', body, onEvent, signal),
  async mindmap(body, signal) {
    const res = await fetch('/api/learn/mindmap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? '请求参数有误' : data.detail
      const err = new Error(detail || `生成思维导图失败（${res.status}）`)
      err.code = data.code
      err.asrEnabled = data.asr_enabled
      err.status = res.status
      if (data.code === 'AUTH_REQUIRED') account.markLoggedOut('expired')
      throw err
    }
    return data
  },
}

export function parseTs(label) {
  if (!label || typeof label !== 'string') return null
  const clean = label.trim().replace(/^\[|\]$/g, '').split(/[,.]/)[0]
  const parts = clean.split(':')
  if (parts.length !== 2 && parts.length !== 3) return null
  if (!parts.every((p) => /^\d+$/.test(p))) return null
  const nums = parts.map(Number)
  if (nums.length === 2) {
    if (nums[1] >= 60) return null
    return nums[0] * 60 + nums[1]
  }
  if (nums[1] >= 60 || nums[2] >= 60) return null
  return nums[0] * 3600 + nums[1] * 60 + nums[2]
}

export function formatTs(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const rem = s % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(rem)}` : `${pad(m)}:${pad(rem)}`
}

export function extractBilibiliBvid(rawUrl) {
  const m = String(rawUrl || '').match(/\b(BV[0-9A-Za-z]{10})\b/)
  return m ? m[1] : null
}

export function extractYoutubeId(rawUrl) {
  const str = String(rawUrl || '')
  const m =
    str.match(/[?&]v=([0-9A-Za-z_-]{11})/) ||
    str.match(/youtu\.be\/([0-9A-Za-z_-]{11})/) ||
    str.match(/youtube\.com\/shorts\/([0-9A-Za-z_-]{11})/)
  return m ? m[1] : null
}

export function platformTimeUrl(rawUrl, seconds) {
  const sec = Math.max(0, Math.floor(Number(seconds) || 0))
  if (!rawUrl) return ''
  try {
    const u = new URL(rawUrl)
    const host = u.hostname.toLowerCase()
    if (host.includes('bilibili.com')) {
      u.searchParams.set('t', String(sec))
      return u.toString()
    }
    if (host.includes('youtube.com') || host.includes('youtu.be')) {
      u.searchParams.set('t', `${sec}s`)
      return u.toString()
    }
    return u.toString()
  } catch {
    return rawUrl
  }
}

export function extractSuggestions(markdown) {
  if (!markdown) return []
  const match = markdown.match(/##\s*(?:启发思考与)?追问建议[\s\S]*$/m)
  if (!match) return []
  const lines = match[0].split(/\r?\n/).slice(1)
  const out = []
  for (const raw of lines) {
    const line = raw.trim()
    if (line.startsWith('## ')) break
    const item = line
      .replace(/^(?:[-*•]|\d+[.、)])\s*/, '')
      .replace(/\[\d{1,2}:\d{2}(?::\d{2})?\]/g, '')
      .replace(/^\*\*|\*\*$/g, '')
      .trim()
    if (item && item.length >= 4 && item.length <= 80 && !item.startsWith('>')) {
      out.push(item)
    }
    if (out.length >= 4) break
  }
  return out
}
