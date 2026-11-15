<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import Icon from './Icon.vue'
import { accountApi } from '../account.js'
import { durationLabel, membership } from '../membership.js'
import { purchaseKind, rememberOrder, submitToGateway } from '../payment.js'

const props = defineProps({ plan: { type: Object, required: true } })
const emit = defineEmits(['close'])
const dialog = ref(null)
const busy = ref(false)
const error = ref('')
const payType = ref('alipay')
let previousOverflow = ''

const kind = computed(() => purchaseKind(membership.data, props.plan.code))
const price = computed(() => (props.plan.price_cents / 100).toFixed(2))
const period = computed(() => (props.plan.months === 12 ? '12 个月' : `${props.plan.months} 个月`))
const expiresText = computed(() => membership.data?.expires_at
  ? new Date(membership.data.expires_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '')
const effect = computed(() => ({
  new: `支付成功后立即生效，有效期 ${period.value}，每月 ${durationLabel(props.plan.monthly_seconds)} 语音识别时长，按开通时间逐月重置，不叠加免费额度。`,
  renew: `在当前到期时间（${expiresText.value}）基础上顺延 ${period.value}，保留原额度周期，不提前重置。`,
  upgrade: `立即升级为年卡：有效期 ${period.value}，月卡剩余有效期自动顺延到年卡之后；本期额度上限提升为 ${durationLabel(props.plan.monthly_seconds)}，保留已用量、预占和原重置日期。`,
  refused: '年卡有效期内不能购买月卡，可直接续费年卡。',
}[kind.value]))

function trapFocus(event) {
  if (event.key !== 'Tab') return
  const controls = [...dialog.value.querySelectorAll('button, a[href], input')].filter((el) => !el.disabled && el.getClientRects().length && (el.type !== 'radio' || el.checked))
  if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus() }
  else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus() }
}

function close() {
  if (!busy.value) emit('close')
}

async function pay() {
  if (busy.value || kind.value === 'refused') return
  busy.value = true
  error.value = ''
  try {
    const { order, action, fields } = await accountApi.createOrder(props.plan.code, payType.value)
    rememberOrder(order.out_trade_no)
    submitToGateway(action, fields)
    // Keep the lock: the browser is leaving for the cashier page.
  } catch (e) {
    error.value = e.message
    busy.value = false
  }
}

onMounted(() => {
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  dialog.value.showModal()
})
onUnmounted(() => { document.body.style.overflow = previousOverflow })
</script>

<template>
  <dialog ref="dialog" aria-labelledby="pay-title" class="upgrade-dialog m-auto w-[calc(100%-2rem)] max-w-3xl rounded-3xl bg-white p-0 shadow-2xl"
    @keydown="trapFocus" @cancel.prevent="close" @click.self="close">
    <div class="p-6">
      <div class="flex items-start justify-between">
        <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-300 to-orange-500 text-white shadow-lg"><Icon name="crown" :size="24" /></span>
        <button type="button" class="flex h-11 w-11 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100 disabled:opacity-50" aria-label="关闭" :disabled="busy" @click="close"><Icon name="x" /></button>
      </div>
      <h3 id="pay-title" class="mt-4 text-xl font-bold text-slate-950">{{ { new: '开通', renew: '续费', upgrade: '升级', refused: '购买' }[kind] }}{{ plan.name }}</h3>
      <dl class="mt-4 text-sm">
        <div class="flex justify-between gap-4"><dt class="text-slate-500">商品</dt><dd class="text-right font-semibold text-slate-800">FreeVideo Pro {{ plan.name }}</dd></div>
      </dl>
      <div class="mt-4 grid items-center gap-5 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:grid-cols-[minmax(0,1fr)_auto]">
      <fieldset class="min-w-0" :disabled="busy">
        <legend class="mb-3 text-sm font-bold text-slate-900">支付方式</legend>
        <div class="grid grid-cols-2 gap-3">
          <label class="relative flex min-h-16 cursor-pointer items-center justify-center gap-2 rounded-2xl border border-blue-500 bg-blue-50 px-3 py-3 font-bold text-blue-600 shadow-sm ring-1 ring-blue-100 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-blue-600">
            <input v-model="payType" type="radio" name="pay-type" value="alipay" class="sr-only" />
            <span aria-hidden="true" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-500 text-lg text-white">支</span>
            <span class="whitespace-nowrap">支付宝</span>
            <Icon name="check" :size="16" class="hidden shrink-0 sm:block" />
          </label>
          <label class="relative flex min-h-16 cursor-not-allowed items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-slate-400">
            <input type="radio" name="pay-type" value="wxpay" disabled class="sr-only" aria-label="微信支付，暂未开放" />
            <span aria-hidden="true" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-500">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C6.5 3 2 6.6 2 11c0 2.4 1.3 4.6 3.5 6L5 21l4-2.3c1 .2 2 .3 3 .3 5.5 0 10-3.6 10-8S17.5 3 12 3Z" /><circle cx="8" cy="10" r="1" fill="white" /><circle cx="15" cy="10" r="1" fill="white" /></svg>
            </span>
            <span class="text-sm font-bold">微信支付<span class="mt-0.5 block text-xs font-normal">暂未开放</span></span>
          </label>
        </div>
      </fieldset>
      <div class="flex items-center justify-between gap-4 sm:pt-7">
        <div class="shrink-0"><p class="text-xs text-slate-500">应付金额</p><p class="mt-1 text-2xl font-extrabold tabular-nums text-slate-950">¥{{ price }}</p></div>
        <button type="button" class="btn-primary flex min-h-12 items-center justify-center gap-2 rounded-xl px-5 text-sm font-bold disabled:opacity-60"
          :disabled="busy || kind === 'refused'" @click="pay">
          <Icon v-if="busy" name="loader" :size="18" class="animate-spin" />{{ busy ? '正在前往收银台…' : '前往支付宝付款' }}
        </button>
      </div>
      </div>
      <p class="mt-4 text-sm leading-relaxed" :class="kind === 'refused' ? 'text-rose-700' : 'text-slate-600'">{{ effect }}</p>
      <p class="mt-2 text-xs leading-relaxed text-slate-500">将跳转到 ZPAY 支付宝收银台付款，完成后自动返回本站确认结果。金额以服务端订单为准。</p>
      <p v-if="error" role="alert" class="mt-3 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-700">{{ error }}</p>
    </div>
  </dialog>
</template>
