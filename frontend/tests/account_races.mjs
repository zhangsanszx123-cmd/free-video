import assert from 'node:assert/strict'
globalThis.BroadcastChannel = class { postMessage() {} }
globalThis.localStorage = { getItem() { return null }, setItem() {}, removeItem() {} }
const { account, accountApi } = await import('../src/account.js')
const user = { id: 1, nickname: 'Tester' }
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
accountApi.login = async () => ({ user })
accountApi.logout = async () => ({ ok: true })
for (const action of ['login', 'logout', 'error']) {
  account.markLoggedOut()
  if (action === 'logout') await account.login({})
  const old = deferred()
  accountApi.me = () => old.promise
  const pending = account.refresh()
  if (action === 'logout') await account.logout()
  else await account.login({})
  if (action === 'error') old.reject(new Error('old failure'))
  else old.resolve({ user: action === 'logout' ? user : null })
  await pending
  assert.equal(account.status, action === 'logout' ? 'guest' : 'authed', action)
}
console.log('PASS: stale guest, identity and error responses are discarded')
const old = deferred(), latest = deferred()
let calls = 0
accountApi.me = () => (++calls === 1 ? old.promise : latest.promise)
const first = account.refresh()
const second = account.refresh(true)
old.resolve({ user: null })
await first
assert.equal(account.refresh(), second, 'old cleanup must preserve the newer pending query')
latest.resolve({ user: { ...user, id: 2 } })
await second
assert.equal(account.user.id, 2)
assert.equal(calls, 2)
console.log('PASS: a newer cross-tab refresh supersedes an in-flight query')
