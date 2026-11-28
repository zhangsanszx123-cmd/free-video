<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { accountApi } from '../account.js'
import Icon from '../components/Icon.vue'

const data = ref(null)
const name = ref('')
const secret = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const pendingRevoke = ref('')
let disposed = false
onUnmounted(() => { disposed = true; secret.value = '' })
const time = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未调用'
async function load() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { const result = await accountApi.apiKeys(); if (!disposed) data.value = result }
  catch (e) { if (!disposed) error.value = e.message }
  finally { if (!disposed) busy.value = false }
}
async function create() {
  if (busy.value || !name.value.trim()) return
  busy.value = true; error.value = ''; notice.value = ''; secret.value = ''
  try {
    const result = await accountApi.createApiKey(name.value.trim())
    if (disposed) return
    secret.value = result.token
    data.value.keys.unshift(result.key)
    name.value = ''
  } catch (e) { if (!disposed) error.value = e.message }
  finally { if (!disposed) busy.value = false }
}
async function revoke(id) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await accountApi.revokeApiKey(id)
    if (disposed) return
    data.value.keys.find(k => k.id === id).revoked_at = new Date().toISOString()
    pendingRevoke.value = ''; secret.value = ''; notice.value = '密钥已撤销，后续调用立即失效。'
  } catch (e) { if (!disposed) error.value = e.message }
  finally { if (!disposed) busy.value = false }
}
async function copy() {
  try { await navigator.clipboard.writeText(secret.value); if (!disposed) notice.value = '已复制，请保存到服务端环境变量。' }
  catch { if (!disposed) notice.value = '无法自动复制，请选中密钥手动复制。' }
}
onMounted(load)
</script>

<template>
  <section class="hero-bg min-h-[calc(100dvh-4rem)] px-4 py-8 sm:py-12">
    <div class="mx-auto max-w-5xl space-y-6">
      <header class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div><RouterLink to="/account" class="text-sm font-semibold text-indigo-600 hover:underline">个人中心 / 开发者</RouterLink>
          <h1 class="mt-3 text-3xl font-extrabold tracking-tight text-slate-950">API 密钥</h1>
          <p class="mt-3 text-sm leading-6 text-slate-600">连接你的应用，让视频文案提取成为工作流的一部分。</p></div>
        <RouterLink to="/account/api/docs" class="btn-primary inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold"><Icon name="file" :size="17" />查看接入文档</RouterLink>
      </header>

      <div class="grid gap-4 sm:grid-cols-3">
        <div v-for="item in [['会员开放', '有效月卡、年卡会员可创建与调用'], ['共享额度', '与网站共用识别时长，平台字幕免费'], ['仅服务端使用', '小程序通过自己的服务端或云函数调用']]" :key="item[0]" class="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 class="font-bold text-slate-900">{{ item[0] }}</h2><p class="mt-2 text-sm leading-6 text-slate-600">{{ item[1] }}</p>
        </div>
      </div>
      <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{{ error }}</p>
      <p v-if="notice" role="status" class="rounded-xl bg-indigo-50 p-4 text-sm text-indigo-800">{{ notice }}</p>
      <div v-if="secret" class="rounded-2xl border border-amber-300 bg-amber-50 p-5" aria-labelledby="secret-title">
        <h2 id="secret-title" class="font-bold text-amber-950">请立即保存：完整密钥仅展示这一次</h2>
        <p class="mt-2 text-sm leading-6 text-amber-900">关闭或离开页面后无法再次查看。请保存在服务端环境变量中，不要放进小程序代码或公开仓库。</p>
        <code class="mt-4 block select-all break-all rounded-xl bg-white p-4 font-mono text-sm text-slate-900">{{ secret }}</code>
        <div class="mt-3 flex flex-wrap gap-2"><button class="min-h-11 rounded-lg bg-amber-900 px-4 text-sm font-semibold text-white hover:bg-amber-800" @click="copy">复制密钥</button>
          <button class="min-h-11 rounded-lg px-4 text-sm font-semibold text-amber-950 hover:bg-amber-100" @click="secret = ''">已保存，关闭展示</button></div>
      </div>
      <section class="glass-card rounded-3xl p-5 sm:p-7" aria-labelledby="create-key-title">
        <h2 id="create-key-title" class="text-lg font-bold text-slate-900">创建密钥</h2>
        <template v-if="data && !data.eligible"><p class="mt-3 text-sm leading-6 text-slate-600">当前账号暂不具备 API 创建权限，开通月卡或年卡即可使用。已受理的任务在保留期内仍可通过有效密钥查询。</p>
          <RouterLink to="/pricing" class="mt-3 inline-flex min-h-11 items-center font-semibold text-indigo-600 hover:underline">查看会员套餐 →</RouterLink></template>
        <form v-else-if="data" class="mt-4" @submit.prevent="create">
          <label for="api-key-name" class="block text-sm font-semibold text-slate-700">密钥名称</label>
          <div class="mt-2 flex flex-col gap-3 sm:flex-row"><input id="api-key-name" v-model="name" maxlength="50" required :disabled="busy" placeholder="例如：微信小程序正式环境" class="min-h-12 min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
            <button :disabled="busy || !name.trim() || data.keys.filter(k => !k.revoked_at).length >= data.max_keys" class="btn-primary min-h-12 rounded-xl px-6 text-sm font-semibold disabled:opacity-50">{{ busy ? '处理中…' : '创建密钥' }}</button></div>
          <p class="mt-2 text-xs leading-6 text-slate-500">最多 {{ data.max_keys }} 把有效密钥。不同应用可分别创建，额度和调用频率按账号合计。</p>
        </form>
      </section>
      <section class="glass-card rounded-3xl p-5 sm:p-7" aria-labelledby="keys-title">
        <div class="flex items-center justify-between gap-3"><h2 id="keys-title" class="text-lg font-bold text-slate-900">我的密钥</h2><button :disabled="busy" class="min-h-11 rounded-xl px-4 text-sm font-semibold text-indigo-600 hover:bg-indigo-50 disabled:opacity-50" @click="load">{{ busy ? '加载中…' : '刷新' }}</button></div>
        <p v-if="!data" class="mt-4 text-sm text-slate-500">{{ busy ? '正在加载密钥…' : '加载未完成，请点击刷新重试。' }}</p>
        <p v-else-if="!data.keys.length" class="mt-4 py-5 text-center text-sm text-slate-500">还没有密钥。创建后即可从服务端发起第一次调用。</p>
        <ul v-else class="mt-3 divide-y divide-slate-100">
          <li v-for="key in data.keys" :key="key.id" class="py-5">
            <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><h3 class="break-all font-semibold text-slate-900">{{ key.name }}</h3><span class="rounded-md px-2 py-1 text-xs" :class="key.revoked_at ? 'bg-slate-100 text-slate-600' : 'bg-emerald-50 text-emerald-800'">{{ key.revoked_at ? '已撤销' : '有效' }}</span></div>
              <code class="mt-2 block text-sm text-slate-600">{{ key.prefix }}••••••••</code><p class="mt-2 text-xs leading-6 text-slate-500">创建于 {{ time(key.created_at) }} · 最近使用：{{ time(key.last_used_at) }}</p></div>
              <button v-if="!key.revoked_at" :disabled="busy" class="min-h-11 self-start rounded-xl px-4 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50" @click="pendingRevoke = key.id">撤销</button></div>
            <div v-if="pendingRevoke === key.id && !key.revoked_at" class="mt-3 rounded-xl bg-rose-50 p-4"><p class="text-sm leading-6 text-rose-900">撤销后使用这把密钥的提交、查询和导出立即失效，已受理任务仍继续处理和结算。</p><div class="mt-2 flex gap-2"><button :disabled="busy" class="min-h-11 rounded-lg bg-rose-700 px-4 text-sm font-semibold text-white disabled:opacity-50" @click="revoke(key.id)">确认撤销</button><button :disabled="busy" class="min-h-11 rounded-lg px-4 text-sm font-semibold text-slate-700" @click="pendingRevoke = ''">取消</button></div></div>
          </li>
        </ul>
      </section>
      <p class="text-sm leading-7 text-slate-600">修改密码、找回密码或账号被禁用后，密钥会被撤销；退出网站登录不影响服务端调用。密钥丢失时请撤销旧密钥并重新创建。</p>
    </div>
  </section>
</template>
