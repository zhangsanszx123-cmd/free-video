/** Offline backend-auth isolation: node frontend/tests/admin_races.mjs [--storage] */
import assert from 'node:assert/strict'
const storage = process.argv.includes('--storage'), channels = new Map(), listeners = new Map()
globalThis.BroadcastChannel = storage ? undefined : class {
  constructor(name) { channels.set(name, this) }
  postMessage() {}
}
globalThis.localStorage = { getItem() { return null }, setItem() {}, removeItem() {} }
globalThis.window = { addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(fn) } }
const { adminAuth, adminRequest, safeAdminRedirect } = await import('../src/admin/adminAuth.js')
const { account, accountApi } = await import('../src/account.js')
const a = { id: 1, username: 'admin_one', nickname: 'Admin A', role: 'superadmin', status: 'active' }
const b = { ...a, id: 2, username: 'admin_two' }
const ok = data => ({ ok: true, status: 200, json: async () => data })
const fail = code => ({ ok: false, status: 401, json: async () => ({ detail: 'expired', code }) })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const reject = promise => promise.then(() => assert.fail('Expected rejection'), error => error)
async function login(admin = a) { globalThis.fetch = async () => ok({ admin }); await adminAuth.login({}) }
function remote(message) {
  if (storage) listeners.get('storage').forEach(fn => fn({ key: 'fv-admin-auth-event', newValue: JSON.stringify(message) }))
  else channels.get('fv-admin-auth').onmessage({ data: message })
}
let passed = 0
async function check(name, run) { await run(); passed++; console.log(`PASS ${name}`) }

await check('front account cannot authorize the backend', async () => {
  account.updateUser({ id: 99, nickname: 'Site user' })
  globalThis.fetch = async () => ok({ admin: null })
  await adminAuth.refresh()
  assert.equal(adminAuth.status, 'guest')
  assert.equal(account.user.id, 99)
})
for (const next of [a, b]) {
  await check(`old 401 cannot expire ${next === a ? 'same' : 'different'} admin login`, async () => {
    await login(a)
    const old = deferred()
    globalThis.fetch = path => path.endsWith('/auth/login') ? Promise.resolve(ok({ admin: next })) : old.promise
    const task = reject(adminRequest('/users'))
    await adminAuth.login({})
    old.resolve(fail('ADMIN_AUTH_REQUIRED'))
    await task
    assert.equal(adminAuth.user.id, next.id)
  })
}
await check('late me cannot replace a new backend session', async () => {
  await login(a)
  const old = deferred()
  globalThis.fetch = path => path.endsWith('/auth/login') ? Promise.resolve(ok({ admin: b })) : old.promise
  const task = adminAuth.refresh()
  await adminAuth.login({})
  old.resolve(ok({ admin: null }))
  await task
  assert.equal(adminAuth.user.id, b.id)
})
await check('current backend 401 expires only backend auth after ordinary refresh', async () => {
  await login(a)
  const old = deferred()
  globalThis.fetch = path => path.endsWith('/auth/me') ? Promise.resolve(ok({ admin: a })) : old.promise
  const task = reject(adminRequest('/users'))
  await adminAuth.refresh()
  old.resolve(fail('ADMIN_AUTH_REQUIRED'))
  await task
  assert.equal(adminAuth.status, 'guest')
  assert.equal(account.user.id, 99)
})
await check('front expiry does not change backend auth', async () => {
  await login(a)
  globalThis.fetch = async () => fail('AUTH_REQUIRED')
  await reject(accountApi.history({ page: 1 }))
  assert.equal(account.status, 'guest')
  assert.equal(adminAuth.user.id, a.id)
})
await check('cross-tab backend session event invalidates 401 before me returns', async () => {
  await login(a)
  const old = deferred(), me = deferred()
  globalThis.fetch = path => path.endsWith('/auth/me') ? me.promise : old.promise
  const task = reject(adminRequest('/users'))
  remote({ type: 'admin-changed', sessionChanged: true })
  old.resolve(fail('ADMIN_AUTH_REQUIRED'))
  await task
  assert.equal(adminAuth.user.id, a.id)
  me.resolve(ok({ admin: b }))
  await adminAuth.ensure()
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(adminAuth.user.id, b.id)
})
await check('role refresh updates permission and page identity', async () => {
  await login(a)
  const version = adminAuth.version
  globalThis.fetch = async () => ok({ admin: { ...a, role: 'admin' } })
  await adminAuth.refresh()
  assert.equal(adminAuth.isSuperadmin, false)
  assert.ok(adminAuth.version > version)
})
await check('backend redirect accepts only backend paths', async () => {
  for (const path of ['https://evil.test', '//evil.test', '/account', '/administrator', '/admin/\\evil', '/admin/login?redirect=/admin/staff']) assert.equal(safeAdminRedirect(path), '/admin/users')
  assert.equal(safeAdminRedirect('/admin/staff?page=2'), '/admin/staff?page=2')
})
console.log(`Backend auth races (${storage ? 'storage' : 'BroadcastChannel'}): ${passed} passed`)
