import assert from 'node:assert/strict'
import {test} from 'node:test'
import {productionOrigin, runtimeConfig, rawEnv, sshSettings} from '../setup-production.mjs'

test('origin accepts HTTPS or a plain HTTP IP and rejects unsafe values', () => {
  assert.equal(productionOrigin('http://43.143.85.207'), 'http://43.143.85.207')
  assert.equal(productionOrigin('https://video.example.com'), 'https://video.example.com')
  for (const bad of ['http://video.example.com', 'http://127.0.0.1', 'https://u:p@video.example.com', 'https://video.example.com/path', 'nonsense']) assert.throws(() => productionOrigin(bad))
})

test('runtime config keeps payments and email verification off over HTTP and secrets out of argv-style fields', () => {
  const values = runtimeConfig({DEEPSEEK_API_KEY: ' key '}, 'http://43.143.85.207', 'p@ss$word"1')
  assert.equal(values.SESSION_SECURE, 'false')
  assert.equal(values.AUTH_EMAIL_VERIFICATION_REQUIRED, 'false')
  assert.equal(values.PUBLIC_BASE_URL, 'http://43.143.85.207')
  assert.equal(values.ALLOWED_ORIGINS, 'http://43.143.85.207')
  assert.equal(values.DEEPSEEK_API_KEY, 'key')
  assert.equal('ZPAY_KEY' in values, false)
  assert.ok(values.SESSION_SECRET.length >= 32)
  assert.ok(rawEnv(values).includes('MYSQL_PASSWORD=p@ss$word"1\n'))
})

test('HTTPS origins enable secure cookies', () => {
  assert.equal(runtimeConfig({}, 'https://video.example.com', 'x'.repeat(16)).SESSION_SECURE, 'true')
})

test('invalid database identity or injected values are rejected', () => {
  assert.throws(() => runtimeConfig({}, 'http://43.143.85.207', ''))
  assert.throws(() => runtimeConfig({}, 'http://43.143.85.207', 'a\nZPAY_KEY=x'))
  assert.throws(() => runtimeConfig({FREEVIDEO_MYSQL_USER: 'root;drop'}, 'http://43.143.85.207', 'secret-value'))
  assert.throws(() => rawEnv({MYSQL_PASSWORD: 'a\nB=1'}))
})

test('SSH destination rejects shell options and injection', () => {
  assert.equal(sshSettings({}).host, '43.143.85.207')
  for (const bad of [{host: '-oProxyCommand=oops'}, {user: 'ubuntu;whoami'}, {port: '70000'}]) assert.throws(() => sshSettings(bad))
})
