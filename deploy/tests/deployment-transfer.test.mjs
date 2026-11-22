import assert from 'node:assert/strict'
import {test} from 'node:test'
import {mkdtemp, writeFile, rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createHash} from 'node:crypto'
import {validateRelease, loadRelease, receiverCommand, retryConnection, sshConnection} from '../send-image.mjs'

const hash = 'a'.repeat(64)
const release = {image: `ghcr.io/zhangsanszx123-cmd/free-video:sha256-${hash}`, imageId: `sha256:${hash}`, archiveSha256: 'b'.repeat(64)}

test('direct release rejects wrong image identities and command injection', () => {
  assert.deepEqual(validateRelease(release), release)
  for (const bad of [{...release, imageId: `sha256:${'c'.repeat(64)}`}, {...release, image: `${release.image};whoami`}, {...release, archiveSha256: '../wrong'}]) assert.throws(() => validateRelease(bad))
  assert.throws(() => receiverCommand('apply', '../escape', release))
  assert.throws(() => receiverCommand('apply;whoami', '1'.repeat(32), release))
  assert.ok(receiverCommand('receive', '1'.repeat(32), release).startsWith('timeout --signal=TERM --kill-after=20s 40m '))
})

test('tampered local image archive fails verification before transfer', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'free-video-transfer-test-'))
  try {
    const data = Buffer.from('fixture-archive-bytes')
    const metadata = {...release, archiveSha256: createHash('sha256').update(data).digest('hex')}
    await writeFile(join(folder, 'image.tar.gz'), data)
    await writeFile(join(folder, 'metadata.json'), JSON.stringify(metadata))
    assert.equal((await loadRelease(folder)).imageId, release.imageId)
    await writeFile(join(folder, 'image.tar.gz'), 'modified-bytes')
    await assert.rejects(loadRelease(folder), /SHA-256/)
  } finally { await rm(folder, {recursive: true, force: true}) }
})

test('transport retries recover without retrying remote deployment errors', async () => {
  let attempts = 0
  const delays = []
  const result = await retryConnection(async () => ({code: ++attempts < 3 ? 255 : 0}), '测试传输', {sleep: async ms => delays.push(ms)})
  assert.equal(result.code, 0)
  assert.equal(attempts, 3)
  assert.deepEqual(delays, [5000, 10000])
  attempts = 0
  await assert.rejects(retryConnection(async () => { attempts++; return {code: 42} }, '测试部署', {sleep: async () => assert.fail('remote error must not retry')}), /42/)
  assert.equal(attempts, 1)
})

test('transport failures have a finite attempt limit', async () => {
  let attempts = 0
  const delays = []
  await assert.rejects(retryConnection(async () => { attempts++; return {code: 255} }, '测试连接', {sleep: async ms => delays.push(ms)}), /255/)
  assert.equal(attempts, 4)
  assert.deepEqual(delays, [5000, 10000, 20000])
})

test('SSH options preserve strict identity checking and reject injected destinations', () => {
  const env = {SSH_HOST: '43.143.85.207', SSH_USER: 'ubuntu', SSH_PORT: '22'}
  assert.ok(sshConnection(env).options.includes('StrictHostKeyChecking=yes'))
  for (const bad of [{...env, SSH_HOST: '-oProxyCommand=oops'}, {...env, SSH_USER: 'ubuntu;whoami'}, {...env, SSH_PORT: '65536'}, {}]) assert.throws(() => sshConnection(bad))
})
