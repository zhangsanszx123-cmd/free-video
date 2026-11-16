/** Offline request/session races: node frontend/tests/auth_request_races.mjs [--storage] */
import assert from 'node:assert/strict'

const channels = []
const broadcasts = []
const useStorage = process.argv.includes('--storage')
let storageHandler
globalThis.BroadcastChannel = useStorage ? undefined : class {
  constructor() { channels.push(this) }
  postMessage(message) { broadcasts.push(message) }
}
globalThis.localStorage = {
  getItem() { return null },
  setItem(key, value) { if (key === 'fv-auth-event') broadcasts.push(JSON.parse(value)) },
  removeItem() {},
}
globalThis.window = {
  location: { href: 'http://127.0.0.1/' },
  addEventListener(name, handler) { if (name === 'storage') storageHandler = handler },
}
function remoteChange(message) {
  if (useStorage) storageHandler({ key: 'fv-auth-event', newValue: JSON.stringify(message) })
  else channels[0].onmessage({ data: message })
}

const { account, accountApi } = await import('../src/account.js')
const { api, downloadArchive } = await import('../src/api.js')
const { learnApi, streamLearnSSE } = await import('../src/learning/learnApi.js')
const firstUser = { id: 1, nickname: 'First user' }
const secondUser = { id: 2, nickname: 'Second user' }
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data })
const unauthorized = () => response({ detail: '登录已过期', code: 'AUTH_REQUIRED' }, 401)
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const entries = [
  ['account API', () => accountApi.history({ page: 1 })],
  ['video API', () => api.transcript({ url: 'https://example.test/video' })],
  ['archive metadata', () => downloadArchive('/api/jobs/test/file', 'test.zip')],
  ['learning SSE', () => streamLearnSSE('/api/learn/summary', {}, () => {})],
  ['learning mindmap', () => learnApi.mindmap({})],
]

async function expectFailure(promise) {
  const error = await promise.then(() => assert.fail('Expected the old request to reject'), error => error)
  assert.match(error.message, /登录已过期/)
}

// Do not short-circuit on the first regression: report every entry before failing the command.
const failures = []
let passed = 0
async function check(name, run) {
  try { await run(); passed++ }
  catch (error) { failures.push(`${name}: ${error.message}`) }
}

for (const [name, request] of entries) {
  for (const sameUser of [false, true]) {
    await check(`${name}: ${sameUser ? 'same-user relogin' : 'another user login'}`, async () => {
      account.updateUser(firstUser)
      const old = deferred()
      const nextUser = sameUser ? firstUser : secondUser
      globalThis.fetch = (path) => path === '/api/auth/login'
        ? Promise.resolve(response({ user: nextUser })) : old.promise
      const pending = expectFailure(request())
      await account.login({})
      const version = account.version
      old.resolve(unauthorized())
      await pending
      assert.equal(account.status, 'authed')
      assert.equal(account.user?.id, nextUser.id)
      assert.equal(account.version, version, 'An old failure must not remount the new session')
    })
  }

  for (const login of ['register', 'verifyEmail']) {
    await check(`${name}: ${login} starts a new session`, async () => {
      account.updateUser(firstUser)
      const old = deferred()
      globalThis.fetch = (path) => String(path).startsWith('/api/auth/')
        ? Promise.resolve(response({ user: firstUser })) : old.promise
      const pending = expectFailure(request())
      await account[login]({})
      old.resolve(unauthorized())
      await pending
      assert.equal(account.status, 'authed')
      assert.equal(account.user?.id, firstUser.id)
    })
  }

  await check(`${name}: session changes while reading the error body`, async () => {
    account.updateUser(firstUser)
    const body = deferred()
    const reading = deferred()
    globalThis.fetch = (path) => path === '/api/auth/login'
      ? Promise.resolve(response({ user: secondUser }))
      : Promise.resolve({ ok: false, status: 401, json() { reading.resolve(); return body.promise } })
    const pending = expectFailure(request())
    await reading.promise
    await account.login({})
    body.resolve({ detail: '登录已过期', code: 'AUTH_REQUIRED' })
    await pending
    assert.equal(account.user?.id, secondUser.id)
  })

  for (const update of ['none', 'me', 'profile']) {
    await check(`${name}: current 401 after ${update}`, async () => {
      account.updateUser(firstUser)
      const old = deferred()
      globalThis.fetch = (path) => path === '/api/auth/me'
        ? Promise.resolve(response({ user: { ...firstUser, nickname: 'Refreshed user' } })) : old.promise
      const pending = expectFailure(request())
      if (update === 'me') await account.refresh()
      if (update === 'profile') account.updateUser({ ...firstUser, nickname: 'Edited nickname' })
      old.resolve(unauthorized())
      await pending
      assert.equal(account.status, 'guest')
      assert.equal(account.logoutReason, 'expired')
    })
  }

  for (const legacy of [false, true]) {
    await check(`${name}: ${legacy ? 'legacy' : 'session'} cross-tab event before me returns`, async () => {
      account.updateUser(firstUser)
      const old = deferred()
      const me = deferred()
      globalThis.fetch = (path) => path === '/api/auth/me' ? me.promise : old.promise
      const pending = expectFailure(request())
      const event = { type: 'auth-changed', userId: firstUser.id, ...(!legacy ? { sessionChanged: true } : {}) }
      remoteChange(event)
      const refreshing = account._pending
      old.resolve(unauthorized())
      await pending
      const preserved = account.status === 'authed' && account.user?.id === firstUser.id
      me.resolve(response({ user: firstUser }))
      await refreshing
      assert.equal(preserved, true, 'A remote session change must invalidate old failures immediately')
      assert.equal(account.status, 'authed')
    })
  }

  await check(`${name}: cross-tab profile update preserves current 401`, async () => {
    account.updateUser(firstUser)
    const old = deferred()
    globalThis.fetch = (path) => path === '/api/auth/me'
      ? Promise.resolve(response({ user: { ...firstUser, nickname: 'Remote nickname' } })) : old.promise
    const pending = expectFailure(request())
    remoteChange({ type: 'auth-changed', userId: firstUser.id, sessionChanged: false })
    await account._pending
    old.resolve(unauthorized())
    await pending
    assert.equal(account.status, 'guest')
    assert.equal(account.logoutReason, 'expired')
  })
}

await check('Broadcasts distinguish login from a profile update', async () => {
  globalThis.fetch = async () => response({ user: firstUser })
  await account.login({})
  assert.equal(broadcasts.at(-1).sessionChanged, true)
  account.updateUser({ ...firstUser, nickname: 'Updated locally' })
  assert.equal(broadcasts.at(-1).sessionChanged, false)
})

console.log(`Request/session races (${useStorage ? 'storage' : 'BroadcastChannel'}): ${passed} passed, ${failures.length} failed`)
if (failures.length) {
  console.error(failures.join('\n'))
  process.exitCode = 1
}
