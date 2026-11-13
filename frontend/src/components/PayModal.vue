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
let previousOverflow = ''

const kind = computed(() => purchaseKind(membership.data, props.plan.code))
const price = computed(() => (props.plan.price_cents / 100).toFixed(2))
const period = computed(() => (props.plan.months === 12 ? '12 个月' : `${props.plan.months} 个月`))
const expiresText = computed(() => membership.data?.expires_at
  ? new Date(membership.data.expires_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '')
const effect = computed(() => ({
  new: `支付成功后立即生效，有效期 ${period.value}，每月 ${durationLabel(props.plan.monthly_seconds)} 语音识别时长。`,
  renew: `在当前到期时间（${expiresText.value}）基础上顺延 ${period.value}。`,
  upgrade: `立即升级为年卡：有效期 ${period.value}，月卡剩余时长自动顺延到年卡之后；本月额度立即提升为 ${durationLabel(props.plan.monthly_seconds)}。`,
  refused: '年卡有效期内不能购买月卡，可直接续费年卡。',
}[kind.value]))

function trapFocus(event) {
  if (event.key !== 'Tab') return
  const controls = [...dialog.value.querySelectorAll('button, a[href]')].filter((el) => !el.disabled && el.getClientRects().length)
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
    const { order, action, fields } = await accountApi.createOrder(props.plan.code)
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
  <dialog ref="dialog" aria-labelledby="pay-title" class="upgrade-dialog m-auto w-[calc(100%-2rem)] max-w-md rounded-3xl bg-white p-0 shadow-2xl"
    @keydown="trapFocus" @cancel.prevent="close" @click.self="close">
    <div class="p-6">
      <div class="flex items-start justify-between">
        <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-300 to-orange-500 text-white shadow-lg"><Icon name="crown" :size="24" /></span>
        <button type="button" class="flex h-11 w-11 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100 disabled:opacity-50" aria-label="关闭" :disabled="busy" @click="close"><Icon name="x" /></button>
      </div>
      <h3 id="pay-title" class="mt-4 text-xl font-bold text-slate-950">{{ { new: '开通', renew: '续费', upgrade: '升级', refused: '购买' }[kind] }}{{ plan.name }}</h3>
      <dl class="mt-4 space-y-3 rounded-2xl bg-slate-50 p-4 text-sm">
        <div class="flex justify-between gap-4"><dt class="text-slate-500">商品</dt><dd class="text-right font-semibold text-slate-800">FreeVideo Pro {{ plan.name }}</dd></div>
        <div class="flex justify-between gap-4"><dt class="text-slate-500">支付方式</dt><dd class="font-semibold text-sky-600">支付宝</dd></div>
        <div class="flex items-baseline justify-between gap-4"><dt class="text-slate-500">应付金额</dt><dd class="text-2xl font-extrabold text-rose-600">¥{{ price }}</dd></div>
      </dl>
      <p class="mt-4 text-sm leading-relaxed" :class="kind === 'refused' ? 'text-rose-700' : 'text-slate-600'">{{ effect }}</p>
      <p class="mt-2 text-xs leading-relaxed text-slate-500">将跳转到 ZPAY 支付宝收银台付款，完成后自动返回本站确认结果。金额以服务端订单为准。</p>
      <p v-if="error" role="alert" class="mt-3 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-700">{{ error }}</p>
      <button type="button" class="btn-primary mt-6 flex min-h-12 w-full items-center justify-center gap-2 rounded-xl font-bold disabled:opacity-60"
        :disabled="busy || kind === 'refused'" @click="pay">
        <Icon v-if="busy" name="loader" :size="18" class="animate-spin" />{{ busy ? '正在前往收银台…' : `前往支付宝付款 ¥${price}` }}
      </button>
    </div>
  </dialog>
</template>
