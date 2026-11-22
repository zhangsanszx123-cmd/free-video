import { readFile, access } from 'node:fs/promises'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { homedir } from 'node:os'
import { parseEnv, parseArgs } from 'node:util'
import { randomBytes } from 'node:crypto'
import { isIP } from 'node:net'
import { Writable } from 'node:stream'
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline/promises'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OPTIONAL_KEYS = ['DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY']

export function productionOrigin(value) {
  let url
  try { url = new URL(value) } catch { throw new Error('请提供完整的网站地址，例如 https://video.example.com 或 http://43.143.85.207。') }
  const hostname = url.hostname.replace(/^\[|\]$/g, '')
  const supported = url.protocol === 'https:' || (url.protocol === 'http:' && isIP(hostname) !== 0)
  const loopback = hostname === 'localhost' || hostname.startsWith('127.') || ['0.0.0.0', '::', '::1'].includes(hostname)
  if (!supported || loopback || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('网站地址须为 HTTPS 或临时 HTTP IP 地址，不含路径或登录信息。')
  }
  return url.origin
}

export function runtimeConfig(env, origin, mysqlPassword) {
  if (!mysqlPassword || /[\r\n\0]/.test(mysqlPassword)) throw new Error('MySQL 密码不能为空或包含换行。')
  const user = env.FREEVIDEO_MYSQL_USER?.trim() || 'freevideo'
  const database = env.FREEVIDEO_MYSQL_DATABASE?.trim() || 'freevideo'
  if (!/^[a-zA-Z0-9_]{1,32}$/.test(user) || !/^[a-zA-Z0-9_]{1,64}$/.test(database)) throw new Error('MySQL 用户名或数据库名无效。')
  const publicOrigin = productionOrigin(origin)
  const values = {
    MYSQL_USER: user,
    MYSQL_PASSWORD: mysqlPassword,
    MYSQL_DATABASE: database,
    SESSION_SECRET: randomBytes(48).toString('base64url'),
    SESSION_SECURE: publicOrigin.startsWith('https:') ? 'true' : 'false',
    PUBLIC_BASE_URL: publicOrigin,
    ALLOWED_ORIGINS: publicOrigin,
    AUTH_EMAIL_VERIFICATION_REQUIRED: 'false',
    ZPAY_MOCK: 'false',
  }
  for (const key of OPTIONAL_KEYS) if (env[key]?.trim()) values[key] = env[key].trim()
  return values
}

export function rawEnv(values) {
  return Object.entries(values).map(([key, value]) => {
    if (!/^[A-Z_]+$/.test(key) || /[\r\n\0]/.test(value)) throw new Error('运行时配置包含不支持的换行或控制字符。')
    return `${key}=${value}`
  }).join('\n') + '\n'
}

export function sshSettings(options) {
  const host = options.host || '43.143.85.207'
  const user = options.user || 'ubuntu'
  const port = options.port || '22'
  if (!/^[a-zA-Z0-9][a-zA-Z0-9.-]*$/.test(host) || !/^[a-z_][a-z0-9_-]*$/.test(user) || !/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    throw new Error('SSH 主机、用户名或端口格式无效。')
  }
  return {host, user, port, key: resolve(options.key || join(homedir(), '.ssh', 'ai-tools-deploy'))}
}

async function localEnvironment() {
  const env = {}
  for (const name of ['backend/.env']) {
    try { Object.assign(env, parseEnv(await readFile(join(root, name), 'utf8'))) }
    catch (error) { if (error.code !== 'ENOENT') throw new Error(`无法读取 ${name}。`) }
  }
  return env
}

async function hiddenPassword(question) {
  if (!process.stdin.isTTY) throw new Error('请在交互终端运行，或设置环境变量 FREEVIDEO_MYSQL_PASSWORD。')
  process.stdout.write(question)
  const muted = new Writable({write(_chunk, _encoding, done) { done() }})
  const prompt = createInterface({input: process.stdin, output: muted, terminal: true})
  try { return await prompt.question('') } finally { prompt.close(); process.stdout.write('\n') }
}

async function main() {
  const {values} = parseArgs({options: {
    origin: {type: 'string'}, host: {type: 'string'}, user: {type: 'string'}, port: {type: 'string'}, key: {type: 'string'},
    'dry-run': {type: 'boolean'}, help: {type: 'boolean'},
  }})
  if (values.help) {
    console.log('node deploy/setup-production.mjs --origin http://43.143.85.207 [--dry-run]\n首次输入网站地址和专用 MySQL 账号密码（隐藏输入，也可用环境变量 FREEVIDEO_MYSQL_PASSWORD）。仅准备服务器环境，不执行发布。\nSSH 默认 ubuntu@43.143.85.207:22，密钥 ~/.ssh/ai-tools-deploy；可用 --host/--user/--port/--key 修改。')
    return
  }
  const ssh = sshSettings(values)
  const env = await localEnvironment()
  const origin = values.origin
  if (!origin) throw new Error('请使用 --origin 指定网站地址。')
  const password = process.env.FREEVIDEO_MYSQL_PASSWORD || (values['dry-run'] ? 'dry-run-placeholder' : await hiddenPassword('专用 MySQL 账号密码（输入不显示）：'))
  const runtime = runtimeConfig({...env, ...process.env}, origin, password)
  const preview = runtime.PUBLIC_BASE_URL.startsWith('http:')
  await access(ssh.key).catch(() => { throw new Error('找不到部署 SSH 私钥，请用 --key 指定文件。') })
  console.log(`目标：${ssh.user}@${ssh.host}:${ssh.port}`)
  console.log(`网站：${runtime.PUBLIC_BASE_URL}`)
  console.log(`数据库：内部网络 mysql:3306，账号 ${runtime.MYSQL_USER}，库 ${runtime.MYSQL_DATABASE}；TLS 证书链校验开启。`)
  console.log(`随配置写入的可选密钥：${OPTIONAL_KEYS.filter(key => runtime[key]).join('、') || '无'}（仅显示名称）。`)
  if (preview) console.log('HTTP IP 模式：支付和邮件验证保持关闭；配置 HTTPS 前，请勿通过公网输入真实账号或支付信息。')
  if (values['dry-run']) {
    console.log('预览通过；未连接服务器，未写入环境文件，未执行部署。')
    return
  }
  const files = {
    RUNTIME_B64: rawEnv(runtime),
    COMPOSE_B64: await readFile(join(root, 'docker-compose.yml'), 'utf8'),
    DEPLOY_B64: await readFile(join(root, 'deploy/deploy.sh'), 'utf8'),
    PASSWORD_B64: runtime.MYSQL_PASSWORD,
  }
  const prefix = Object.entries(files).map(([key, value]) => `${key}='${Buffer.from(value).toString('base64')}'`).join('\n')
  const remote = await readFile(join(root, 'deploy/setup-server.sh'), 'utf8')
  const input = `${prefix}\nMYSQL_USER_NAME='${runtime.MYSQL_USER}'\nMYSQL_DB_NAME='${runtime.MYSQL_DATABASE}'\n${remote.replace(/\r\n/g, '\n')}`
  const args = ['-i', ssh.key, '-p', ssh.port, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15', `${ssh.user}@${ssh.host}`]
  const setupStatus = await new Promise((done, fail) => {
    const child = spawn('ssh', [...args, 'bash -s'], {stdio: ['pipe', 'inherit', 'inherit'], shell: false})
    child.on('error', () => fail(new Error('无法启动 SSH，请确认本机已安装 OpenSSH。')))
    child.stdin.on('error', () => {})
    child.on('exit', code => (code === 0 || code === 20) ? done(code) : fail(new Error('服务器初始化未完成，请查看上方不含密码的检查结果。')))
    child.stdin.end(input)
  })
  if (setupStatus === 20) { console.log('保留已有生产部署，本次未改变运行配置。'); return }
  console.log('\n初始化完成。1Panel 反向代理目标：http://127.0.0.1:13001')
  if (preview) console.log(`在 1Panel 使用 IP ${new URL(runtime.PUBLIC_BASE_URL).hostname} 端口 80 创建 HTTP 反向代理网站。`)
  else console.log(`网站使用 ${runtime.PUBLIC_BASE_URL}，在 1Panel 启用 HTTPS。`)
  console.log('接下来推送到 main，由 GitHub Actions 构建并部署。管理员账号需另行用 python -m app.admin_auth bootstrap 创建。')
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1 })
}
