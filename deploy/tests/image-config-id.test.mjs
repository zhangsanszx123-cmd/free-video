import assert from 'node:assert/strict'
import {test} from 'node:test'
import {mkdtemp, mkdir, writeFile, readFile, rm} from 'node:fs/promises'
import {join, resolve} from 'node:path'
import {tmpdir} from 'node:os'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'

const python = process.platform === 'win32' ? 'python' : 'python3'
const helper = resolve('deploy/image-config-id.py')
async function fixture(change = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'free-video-image-config-'))
  const content = JSON.stringify({architecture: 'amd64', os: 'linux', config: {Env: ['NODE_ENV=production']}, rootfs: {type: 'layers', diff_ids: []}, ...change})
  const digest = createHash('sha256').update(content).digest('hex')
  await mkdir(join(directory, 'blobs', 'sha256'), {recursive: true})
  await writeFile(join(directory, 'blobs', 'sha256', digest), content)
  await writeFile(join(directory, 'manifest.json'), JSON.stringify([{Config: `blobs/sha256/${digest}`, RepoTags: ['example/image:release'], Layers: []}]))
  await writeFile(join(directory, 'index.json'), JSON.stringify({manifests: [{digest: `sha256:${'b'.repeat(64)}`}]}))
  const archive = join(directory, 'image.tar')
  const pack = () => execFileSync('tar', ['-cf',archive,'-C',directory,'manifest.json','index.json','blobs'])
  pack()
  return {directory, archive, pack, expected: `sha256:${digest}`}
}

test('portable image identity hashes config bytes instead of storage-backend manifest ID', async () => {
  const data = await fixture()
  try {
    assert.equal(execFileSync(python, [helper,data.archive], {encoding:'utf8'}).trim(), data.expected)
    assert.equal(execFileSync(python, [helper,'-'], {input:await readFile(data.archive),encoding:'utf8'}).trim(), data.expected)
    await writeFile(join(data.directory, 'manifest.json'), JSON.stringify([{Config:`blobs/sha256/${data.expected.slice(7)}`,RepoTags:['example/image:different-tag'],Layers:[]}]))
    data.pack()
    assert.equal(execFileSync(python, [helper,data.archive], {encoding:'utf8'}).trim(), data.expected)
  } finally { await rm(data.directory, {recursive:true,force:true}) }
})

test('portable image identity rejects a missing or traversing config target', async () => {
  const data = await fixture()
  try {
    for (const path of ['blobs/sha256/missing','../outside.json']) {
      await writeFile(join(data.directory, 'manifest.json'), JSON.stringify([{Config:path,RepoTags:[],Layers:[]}]))
      data.pack()
      assert.throws(() => execFileSync(python, [helper,data.archive], {stdio:'pipe'}))
    }
  } finally { await rm(data.directory, {recursive:true,force:true}) }
})

test('portable image identity rejects another architecture', async () => {
  const data = await fixture({architecture:'arm64'})
  try { assert.throws(() => execFileSync(python,[helper,data.archive],{stdio:'pipe'})) }
  finally { await rm(data.directory,{recursive:true,force:true}) }
})
