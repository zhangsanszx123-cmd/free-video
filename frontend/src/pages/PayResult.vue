<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { accountApi } from '../account.js'
import { loadMembership } from '../membership.js'
import { lastOrder } from '../payment.js'

const POLL_MS = 2000
const MAX_POLLS = 60
const route = useRoute()
// ZPAY appends out_trade_no (and a signature we do not need) to return_url; the server state is authoritative.
const number = String(route.query.out_trade_no || lastOrder() || '')
const order = ref(null)
const error = ref('')
const polls = ref(0)
const checking = ref(false)
let timer
let disposed = false

const state = computed(() => {
  if (!number) return 'missing'
  if (!order.value) return error.value ? 'error' : 'checking'
  if (order.value.status === 'pending') return polls.value >= MAX_POLLS ? 'timeout' : 'checking'
  return order.value.status
})
const fmt = (iso) => (iso ? new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '')

async function check() {
  clearTimeout(timer)
  if (!number || disposed) return
  checking.value = true
  try {
    order.value = await accountApi.order(number)
    error.value = ''
  } catch (e) {
    error.value = e.message
    if (e.status === 404) return
  } finally {
    checking.value = false
  }
  if (disposed) return
  if (order.value && order.value.status !== 'pending') {
    if (order.value.status === 'paid') loadMembership()
    return
  }
  polls.value += 1
  if (polls.value < MAX_POLLS) timer = setTimeout(check, POLL_MS)
}

function retry() {
  polls.value = 0
  check()
}

onMounted(check)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>

<template>
  <section class="hero-bg min-h-[calc(100dvh-4rem)] px-4 py-12 sm:py-16">
    <div class="glass-card mx-auto max-w-lg rounded-3xl p-6 text-center sm:p-10" aria-live="polite">
      <template v-if="state === 'paid'">
        <span class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100 text-emerald-600"><Icon name="check" :size="32" /></span>
        <h1 class="mt-5 text-2xl font-extrabold text-slate-950">支付成功，会员已开通</h1>
        <p class="mt-3 text-sm leading-6 text-slate-600">{{ order.plan_name }} 有效期至 {{ fmt(order.membership_expires_at) }}（北京时间）</p>
      </template>
      <template v-else-if="state === 'refund_required' || state === 'refunded'">
        <span class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-amber-100 text-amber-600"><Icon name="alert" :size="32" /></span>
        <h1 class="mt-5 text-2xl font-extrabold text-slate-950">{{ state === 'refunded' ? '该订单已退款' : '已收到付款，等待退款' }}</h1>
        <p class="mt-3 text-sm leading-6 text-slate-600">该订单与当前会员规则冲突（例如年卡有效期内购买了月卡），未重复开通会员。款项不会丢失，管理员会原路全额退款。</p>
      </template>
      <template v-else-if="state === 'checking'">
        <span class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-indigo-100 text-indigo-600"><Icon name="loader" :size="32" class="animate-spin" /></span>
        <h1 class="mt-5 text-2xl font-extrabold text-slate-950">正在确认支付结果…</h1>
        <p class="mt-3 text-sm leading-6 text-slate-600">正在向支付平台核实订单，请勿重复付款。</p>
      </template>
      <template v-else-if="state === 'timeout'">
        <span class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-slate-100 text-slate-500"><Icon name="clock" :size="32" /></span>
        <h1 class="mt-5 text-2xl font-extrabold text-slate-950">暂未查询到付款</h1>
        <p class="mt-3 text-sm leading-6 text-slate-600">如果你已经完成付款，系统会在后台自动核对并开通，可稍后在个人中心查看订单。若未付款，可返回定价页重新发起。</p>
      </template>
      <template v-else>
        <span class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-rose-100 text-rose-600"><Icon name="alert" :size="32" /></span>
        <h1 class="mt-5 text-2xl font-extrabold text-slate-950">{{ state === 'missing' ? '没有找到订单' : '查询订单失败' }}</h1>
        <p class="mt-3 text-sm leading-6 text-slate-600">{{ error || '请从个人中心「会员与额度」查看最近订单。' }}</p>
      </template>
      <p v-if="number" class="mt-4 break-all text-xs text-slate-400">订单号 {{ number }}</p>
      <div class="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-center">
        <button v-if="state === 'timeout' || state === 'error'" type="button" class="btn-primary min-h-11 rounded-xl px-5 font-bold disabled:opacity-60" :disabled="checking" @click="retry">{{ checking ? '查询中…' : '我已付款，重新检查' }}</button>
        <RouterLink to="/account?section=membership" class="btn-ghost flex min-h-11 items-center justify-center px-5 font-semibold">查看会员与订单</RouterLink>
        <RouterLink v-if="state !== 'paid'" to="/pricing" class="btn-ghost flex min-h-11 items-center justify-center px-5 font-semibold">返回定价页</RouterLink>
      </div>
    </div>
  </section>
</template>
