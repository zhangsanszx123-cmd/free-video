// Node.js 22+ (built-in fetch). Run ONLY on your server, never in a Mini Program.
// Set FREEVIDEO_BASE_URL (ends /api/open/v1), FREEVIDEO_API_KEY.
// New: FREEVIDEO_URL + persisted FREEVIDEO_IDEMPOTENCY_KEY; resume: FREEVIDEO_TASK_ID.
const env = process.env
const base = (env.FREEVIDEO_BASE_URL || '').replace(/\/$/, '')
if (!env.FREEVIDEO_API_KEY || !base) throw new Error('Set FREEVIDEO_BASE_URL and FREEVIDEO_API_KEY')
const parsed = new URL(base)
if (parsed.username || parsed.password || (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(parsed.hostname)))) throw new Error('Use HTTPS in production')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
async function call(path, body) {
  const headers = { Authorization: `Bearer ${env.FREEVIDEO_API_KEY}` }
  if (body) {
    headers['Content-Type'] = 'application/json'
    headers['Idempotency-Key'] = env.FREEVIDEO_IDEMPOTENCY_KEY
  }
  let res
  try { res = await fetch(base + path, { method: body ? 'POST' : 'GET', headers, body: body && JSON.stringify(body), signal: AbortSignal.timeout(20000), redirect: 'error' }) }
  catch { throw { temporary: true, delay: 5000 } }
  if ([429, 502, 503, 504].includes(res.status)) {
    const seconds = Number(res.headers.get('Retry-After')) || 5
    throw { temporary: true, delay: Math.max(1, Math.min(60, seconds)) * 1000 }
  }
  const data = await res.json()
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${data.error?.message || 'Request failed'}`)
  return data.data
}
async function main() {
  let taskId = env.FREEVIDEO_TASK_ID
  if (!taskId) {
    if (!env.FREEVIDEO_URL || !env.FREEVIDEO_IDEMPOTENCY_KEY) throw new Error('Persist FREEVIDEO_IDEMPOTENCY_KEY and set FREEVIDEO_URL before submitting')
    const body = { url: env.FREEVIDEO_URL, allow_asr: env.FREEVIDEO_ALLOW_ASR === 'true' }
    for (let attempt = 0; attempt < 3; attempt++) {
      try { taskId = (await call('/transcriptions', body)).task_id; break }
      catch (e) { if (!e.temporary) throw e; await sleep(e.delay) }
    }
    if (!taskId) throw new Error('Submission not confirmed. Retry with the SAME persisted key and parameters')
  }
  console.log(`task_id=${taskId}`) // persist to resume querying later
  const deadline = Date.now() + 300000
  while (Date.now() < deadline) {
    let data
    try { data = await call(`/transcriptions/${encodeURIComponent(taskId)}`) }
    catch (e) { if (!e.temporary) throw e; await sleep(e.delay); continue }
    if (data.status === 'succeeded') { console.log(JSON.stringify(data, null, 2)); return }
    if (['failed', 'uncertain'].includes(data.status)) {
      console.log(JSON.stringify(data, null, 2))
      throw new Error('Inspect the original task. NEVER automatically resubmit uncertain audio')
    }
    await sleep(5000)
  }
  throw new Error('Polling stopped. Resume with FREEVIDEO_TASK_ID; do not create a replacement task')
}
main().catch(e => { console.error(e.message || 'Request interrupted; keep original task/key'); process.exitCode = 1 })
