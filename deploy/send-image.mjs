import {createReadStream} from 'node:fs'
import {readFile, stat, mkdtemp, rm, access} from 'node:fs/promises'
import {createHash, randomBytes} from 'node:crypto'
import {homedir, tmpdir} from 'node:os'
import {join, resolve, dirname} from 'node:path'
import {fileURLToPath, pathToFileURL} from 'node:url'
import {parseArgs} from 'node:util'
import {spawn} from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const receiver = '/opt/projects/free-video/deploy/receive-release.sh'

export function validateRelease(value) {
  const imageId = value?.imageId
  if (typeof imageId !== 'string' || !/^sha256:[a-f0-9]{64}$/.test(imageId)) throw new Error('镜像 ID 元数据无效。')
  if (value.image !== `ghcr.io/zhangsanszx123-cmd/free-video:sha256-${imageId.slice(7)}`) throw new Error('镜像标签与内容 ID 不一致。')
  if (typeof value.archiveSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.archiveSha256)) throw new Error('镜像压缩包校验值无效。')
  return {image: value.image, imageId, archiveSha256: value.archiveSha256}
}

export async function sha256File(file) {
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  return hash.digest('hex')
}

export async function loadRelease(directory) {
  const metadata = validateRelease(JSON.parse(await readFile(join(directory, 'metadata.json'), 'utf8')))
  const archive = join(directory, 'image.tar.gz')
  if (!(await stat(archive)).isFile() || (await stat(archive)).size === 0) throw new Error('镜像压缩包缺失或为空。')
  if (await sha256File(archive) !== metadata.archiveSha256) throw new Error('本地镜像压缩包 SHA-256 不一致，停止发布。')
  return {...metadata, archive}
}

export function sshConnection(env, key = join(homedir(), '.ssh', 'id_ed25519')) {
  const host = env.SSH_HOST || '', user = env.SSH_USER || '', port = env.SSH_PORT || '22'
  if (!/^[a-zA-Z0-9][a-zA-Z0-9.-]*$/.test(host) || !/^[a-z_][a-z0-9_-]*$/.test(user) || !/^\d+$/.test(port) || +port < 1 || +port > 65535) throw new Error('SSH 主机、用户或端口无效。')
  return {
    destination: `${user}@${host}`, key: resolve(key), port,
    options: ['-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=20','-o','ConnectionAttempts=1','-o','ServerAliveInterval=20','-o','ServerAliveCountMax=6'],
  }
}

export function receiverCommand(mode, transfer, release) {
  if (!['receive','apply','status'].includes(mode) || !/^[a-f0-9]{32}$/.test(transfer)) throw new Error('无效的镜像传输操作。')
  validateRelease(release)
  const args = [mode, transfer, release.image, release.imageId, release.archiveSha256].map(value => `'${value}'`).join(' ')
  const limit = {receive: '40m', apply: '15m', status: '1m'}[mode]
  return `timeout --signal=TERM --kill-after=20s ${limit} bash ${receiver} ${args}`
}

export async function retryConnection(operation, label, {attempts = 4, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), retryCodes = [255]} = {}) {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const result = await operation()
    if (result.code === 0) return result
    if (!retryCodes.includes(result.code) || attempt === attempts) throw new Error(`${label}失败（退出码 ${result.code}）。`)
    const delay = 5000 * 2 ** (attempt - 1)
    console.log(`${label}连接中断，${delay / 1000} 秒后重试（${attempt}/${attempts}）。`)
    await sleep(delay)
  }
}

function execute(program, args, {inputFile, capture = false, onChild} = {}) {
  return new Promise((done, fail) => {
    const child = spawn(program, args, {shell: false, stdio: [inputFile ? 'pipe' : 'ignore', capture ? 'pipe' : 'inherit', 'inherit']})
    onChild?.(child)
    let output = '', stream, timer
    const started = Date.now()
    let sent = 0
    if (capture) child.stdout.on('data', data => { output += data.toString(); if (output.length > 65536) child.kill('SIGTERM') })
    if (inputFile) {
      stream = createReadStream(inputFile.path)
      stream.on('data', data => { sent += data.length })
      stream.on('error', () => child.kill('SIGTERM'))
      child.stdin.on('error', () => stream.destroy())
      stream.pipe(child.stdin)
      timer = setInterval(() => {
        const elapsed = Math.max((Date.now() - started) / 1000, 0.001)
        const rate = sent / elapsed
        const eta = rate > 0 ? Math.ceil(Math.max(inputFile.size - sent, 0) / rate) : '?'
        console.log(`镜像传输 ${(sent / 1048576).toFixed(1)}/${(inputFile.size / 1048576).toFixed(1)} MiB (${Math.min(100, sent / inputFile.size * 100).toFixed(0)}%)，平均 ${(rate / 1048576).toFixed(2)} MiB/s，预计剩余 ${eta} 秒`)
      }, 5000)
    }
    child.once('error', () => { clearInterval(timer); stream?.destroy(); fail(new Error(`无法启动 ${program}。`)) })
    child.once('close', (code, signal) => {
      clearInterval(timer)
      stream?.destroy()
      onChild?.(undefined)
      done({code: code ?? (signal === 'SIGINT' ? 130 : 143), stdout: output.trim()})
    })
  })
}

async function main() {
  const {values} = parseArgs({options: {directory: {type: 'string', default: 'release-image'}, key: {type: 'string'}, help: {type: 'boolean'}}})
  if (values.help) { console.log('node deploy/send-image.mjs --directory release-image [--key SSH_PRIVATE_KEY_FILE]\n从 SSH_HOST/SSH_PORT/SSH_USER 读取连接参数，传输已构建镜像，不上传环境文件。'); return }
  const release = await loadRelease(resolve(values.directory))
  const connection = sshConnection(process.env, values.key)
  await access(connection.key)
  const transfer = randomBytes(16).toString('hex')
  const stage = await mkdtemp(join(tmpdir(), 'free-video-release-'))
  let activeChild, aborted = false
  const interrupt = () => { aborted = true; activeChild?.kill('SIGTERM') }
  process.once('SIGINT', interrupt)
  process.once('SIGTERM', interrupt)
  const onChild = child => { activeChild = child }
  const run = (program, args, options) => {
    if (aborted) throw new Error('发布已中止。')
    return execute(program, args, {...options, onChild})
  }
  const ssh = (command, options) => run('ssh', ['-i',connection.key,'-p',connection.port,...connection.options,connection.destination,command], options)
  const status = async () => {
    let state
    await retryConnection(async () => {
      const result = await ssh(receiverCommand('status', transfer, release), {capture: true})
      if (result.code === 255) return result
      if (!['deployed','received','missing'].includes(result.stdout)) throw new Error('服务器返回了无效的发布状态。')
      state = result.stdout
      if (result.code !== {deployed: 0, received: 1, missing: 2}[state]) throw new Error('服务器发布状态与退出码不一致。')
      return {code: 0}
    }, '查询发布状态')
    return state
  }
  try {
    const config = join(stage, 'release-config.tar.gz')
    const packed = await run('tar', ['-czf',config,'-C',root,'docker-compose.yml','deploy/deploy.sh','deploy/receive-release.sh','deploy/image-config-id.py'])
    if (packed.code !== 0) throw new Error('部署配置打包失败。')
    await retryConnection(() => run('scp', ['-i',connection.key,'-P',connection.port,...connection.options,config,`${connection.destination}:/opt/projects/free-video/deploy/release-config.tar.gz`]), '上传部署配置', {retryCodes: [1,255]})
    await retryConnection(() => ssh('cd /opt/projects/free-video && tar -xzf deploy/release-config.tar.gz'), '安装部署配置')
    const size = (await stat(release.archive)).size
    console.log(`准备直接传输 ${(size / 1048576).toFixed(1)} MiB 镜像，服务器无需访问 GHCR。`)
    await retryConnection(async () => {
      const state = await status()
      if (state !== 'missing') return {code: 0}
      return ssh(receiverCommand('receive', transfer, release), {inputFile: {path: release.archive, size}})
    }, '上传镜像')
    let interruptions = 0
    const applyStarted = Date.now()
    while (true) {
      const state = await status()
      if (state === 'deployed') break
      if (state !== 'received') throw new Error('服务器缺少已验证的镜像归档，停止更新。')
      console.log('镜像已接收并校验，开始导入和容器健康检查。')
      const result = await ssh(receiverCommand('apply', transfer, release))
      if (result.code === 0) {
        if (await status() !== 'deployed') throw new Error('服务器未确认应用健康，不能将发布标记为成功。')
        break
      }
      if (result.code !== 75 && result.code !== 255) throw new Error(`服务器导入或部署失败（退出码 ${result.code}）。`)
      if (result.code === 255 && ++interruptions >= 4) throw new Error('发布连接多次中断，请检查任务日志及服务器状态。')
      if (Date.now() - applyStarted > 20 * 60 * 1000) throw new Error('等待服务器发布锁超时。')
      await new Promise(resolve => setTimeout(resolve, 10000))
    }
    console.log(`部署完成且健康：${release.image}`)
  } finally {
    process.removeListener('SIGINT', interrupt)
    process.removeListener('SIGTERM', interrupt)
    await rm(stage, {recursive: true, force: true})
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1 })
}
