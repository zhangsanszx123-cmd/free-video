<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import AdminDialog from '../components/AdminDialog.vue'
import { adminApi } from '../adminApi.js'
import { adminAuth } from '../adminAuth.js'

const plans = ref([]), loading = ref(false), busy = ref(false)
const error = ref(''), notice = ref(''), editing = ref(null), amount = ref(''), confirmation = ref(null)
const controller = new AbortController()
let disposed = false
onUnmounted(() => { disposed = true; controller.abort() })
async function load() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await adminApi.plans(controller.signal)
    if (!disposed) plans.value = data.plans
  } catch (e) { if (!disposed) error.value = e.message }
  finally { loading.value = false }
}
onMounted(load)
function edit(plan) {
  editing.value = { ...plan }
  amount.value = (plan.price_cents / 100).toFixed(2)
  error.value = ''; notice.value = ''; confirmation.value = null
}
function review() {
  const value = amount.value.trim()
  if (!/^\d{1,6}(\.\d{1,2})?$/.test(value)) { error.value = '请输入 0.01–999999.99 元，最多两位小数'; return }
  const [whole, fraction = ''] = value.split('.')
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, '0'))
  if (cents < 1) { error.value = '价格不能低于 0.01 元'; return }
  if (cents === editing.value.price_cents) { error.value = '价格未发生变化'; return }
  error.value = ''
  confirmation.value = cents
}
async function save() {
  if (busy.value || confirmation.value === null) return
  busy.value = true
  try {
    const { plan } = await adminApi.planPrice(editing.value.code,
      { price_cents: confirmation.value, revision: editing.value.revision }, controller.signal)
    if (disposed) return
    plans.value = plans.value.map(item => item.code === plan.code ? plan : item)
    editing.value = null; confirmation.value = null
    notice.value = '价格已保存，前台将在 30 秒内同步；新订单使用新价格。'
  } catch (e) {
    if (!disposed) {
      if (e.code === 'ADMIN_PLAN_CONFLICT') {
        editing.value = null; confirmation.value = null
        await load()
      }
      error.value = e.message
    }
  } finally { busy.value = false }
}
</script>

<template>
  <section class="max-w-4xl">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div><h1 class="text-2xl font-extrabold">会员价格管理</h1><p class="mt-2 text-sm leading-6 text-slate-500">管理月卡与年卡售价，保存后自动同步至前台。</p></div>
      <button class="min-h-11 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold disabled:opacity-50" :disabled="loading || busy" @click="load">{{ loading ? '刷新中…' : '刷新价格' }}</button>
    </div>
    <p v-if="!adminAuth.isSuperadmin" class="mt-5 rounded-xl bg-indigo-50 p-4 text-sm text-indigo-800">当前账号可查看价格，仅超级管理员可以修改。</p>
    <p v-if="notice" role="status" class="mt-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800">{{ notice }}</p>
    <p v-if="error && !editing" role="alert" class="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{{ error }}</p>
    <p v-if="loading && !plans.length" role="status" class="py-8 text-sm text-slate-500">正在加载价格…</p>
    <div class="mt-6 grid gap-5 sm:grid-cols-2">
      <article v-for="plan in plans" :key="plan.code" class="rounded-2xl border border-slate-200 bg-white p-6">
        <h2 class="text-lg font-bold">{{ plan.name }}</h2>
        <p class="mt-5 flex flex-wrap items-baseline gap-2"><span class="text-3xl font-extrabold tabular-nums">¥{{ (plan.price_cents / 100).toFixed(2) }}</span><span class="text-sm text-slate-500">/ {{ plan.code === 'monthly' ? '月' : '年' }}</span></p>
        <button v-if="adminAuth.isSuperadmin" class="btn-primary mt-6 min-h-12 w-full rounded-xl font-bold" @click="edit(plan)">修改{{ plan.code === 'monthly' ? '月卡' : '年卡' }}价格</button>
      </article>
    </div>
    <p class="mt-6 text-sm leading-7 text-slate-500">改价只影响新订单，已创建的订单保留原金额。会员有效期和使用额度保持原配置，已有会员权益不受影响。价格修改会记录操作者及修改前后的金额。</p>
    <AdminDialog v-if="editing" :title="confirmation === null ? `修改${editing.name}价格` : '确认修改价格'" :busy="busy" @close="editing = null">
      <form class="space-y-5" @submit.prevent="confirmation === null ? review() : save()">
        <template v-if="confirmation === null">
          <p class="text-sm text-slate-500">当前售价：¥{{ (editing.price_cents / 100).toFixed(2) }}</p>
          <label class="block text-sm font-semibold">新价格（元）<input v-model="amount" aria-label="新价格（元）" inputmode="decimal" maxlength="9" autofocus class="input-control mt-2 min-h-12 w-full rounded-xl border border-slate-200 px-4" placeholder="例如 19.90" /></label>
        </template>
        <div v-else class="rounded-xl bg-indigo-50 p-4 text-sm leading-7 text-indigo-900">
          <p class="font-bold">{{ editing.name }}</p><p>原价：¥{{ (editing.price_cents / 100).toFixed(2) }}</p><p>新价：<strong>¥{{ (confirmation / 100).toFixed(2) }}</strong></p><p class="mt-2">保存后新订单使用此价格，请核对金额。</p>
        </div>
        <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ error }}</p>
        <button class="btn-primary min-h-12 w-full rounded-xl font-bold" :disabled="busy">{{ busy ? '保存中…' : confirmation === null ? '下一步，确认价格' : '确认保存价格' }}</button>
        <button v-if="confirmation !== null" type="button" :disabled="busy" class="min-h-11 w-full text-sm font-semibold text-slate-600" @click="confirmation = null">返回修改</button>
      </form>
    </AdminDialog>
  </section>
</template>
