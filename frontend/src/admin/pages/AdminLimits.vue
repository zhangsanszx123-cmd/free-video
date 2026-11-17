<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import Icon from '../../components/Icon.vue'
import AdminDialog from '../components/AdminDialog.vue'
import { adminApi } from '../adminApi.js'
import { adminAuth } from '../adminAuth.js'

const plans = ref([]), ceilings = ref({}), loading = ref(false), saving = ref(false)
const error = ref(''), notice = ref(''), selected = ref('free'), editing = ref(null), confirming = ref(false)
const draft = reactive({}), errors = reactive({})
const controller = new AbortController()
let disposed = false
onUnmounted(() => { disposed = true; controller.abort() })
const fields = computed(() => [
  { key: 'monthly_minutes', label: '视频转文字时长', unit: '分钟 / 月', max: 525600, icon: 'clock', hint: '每个额度周期可用的识别总时长' },
  { key: 'ai_monthly_limit', label: 'AI 视频总结', unit: '个视频 / 周期', max: 1000000, icon: 'sparkles', hint: '同一视频在本周期内重复总结不重复计次' },
  { key: 'chat_daily_limit', label: 'AI 追问', unit: '条 / 天', max: 1000000, icon: 'chat', hint: '每天北京时间 0 点重置' },
  { key: 'batch_max_links', label: '批量提取', unit: '条链接 / 次', max: ceilings.value.batch_max_links || 1, icon: 'layers', hint: '一次批量任务允许提交的链接数' },
  { key: 'asr_max_minutes', label: '单条语音识别最长', unit: '分钟 / 视频', max: ceilings.value.asr_max_minutes || 1, icon: 'mic', hint: '每条视频可发起语音识别的时长上限' },
])
const valueOf = (plan, field) => field.key === 'monthly_minutes' ? plan.monthly_seconds / 60 : plan[field.key]
const valueLabel = (plan, field) => field.key === 'monthly_minutes' && plan.monthly_seconds % 3600 === 0
  ? `${plan.monthly_seconds / 3600} 小时` : `${valueOf(plan, field)} ${field.unit.split(' / ')[0]}`
const active = computed(() => plans.value.find(plan => plan.code === selected.value))
const changes = computed(() => editing.value ? fields.value.filter(field => Number(draft[field.key]) !== valueOf(editing.value, field)) : [])
async function load() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try {
    const data = await adminApi.planLimits(controller.signal)
    if (!disposed) { plans.value = data.plans; ceilings.value = data.ceilings }
  } catch (e) { if (!disposed) error.value = e.message }
  finally { loading.value = false }
}
onMounted(load)
function edit(plan) {
  editing.value = { ...plan }; confirming.value = false; error.value = ''; notice.value = ''
  for (const field of fields.value) { draft[field.key] = String(valueOf(plan, field)); errors[field.key] = '' }
}
function validate(field) {
  const text = String(draft[field.key]).trim()
  errors[field.key] = /^\d+$/.test(text) && Number(text) >= 1 && Number(text) <= field.max ? '' : `请输入 1–${field.max} 的整数`
  return !errors[field.key]
}
function review() {
  const valid = fields.value.map(validate).every(Boolean)
  if (!valid) return
  if (!changes.value.length) { error.value = '额度未发生变化'; return }
  error.value = ''; confirming.value = true
}
async function save() {
  if (saving.value) return
  saving.value = true
  const name = editing.value.name
  try {
    const body = { revision: editing.value.revision, ...Object.fromEntries(fields.value.map(field => [field.key, Number(draft[field.key])])) }
    const { plan } = await adminApi.updatePlanLimits(editing.value.code, body, controller.signal)
    if (disposed) return
    plans.value = plans.value.map(item => item.code === plan.code ? plan : item)
    editing.value = null
    notice.value = `${name}额度已更新，已对该套餐用户生效。`
  } catch (e) {
    if (!disposed) {
      if (e.code === 'ADMIN_PLAN_CONFLICT') { editing.value = null; await load() }
      error.value = e.message
    }
  } finally { saving.value = false }
}
</script>

<template>
  <section class="limits-page max-w-6xl">
    <header class="admin-page-head"><span class="admin-page-icon"><Icon :size="20" name="clock" /></span><div class="min-w-0"><h1 class="text-xl font-bold leading-tight tracking-tight text-slate-950">套餐额度管理</h1><p class="mt-0.5 text-xs leading-5 text-slate-500 sm:text-sm">对照三档套餐，调整用户可使用的功能额度。</p></div><div class="ml-auto flex shrink-0 items-center gap-2"><button type="button" :disabled="loading || saving" class="flex min-h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 disabled:opacity-50" @click="load"><Icon name="refresh" :size="16" />{{ loading ? '刷新中…' : '刷新额度' }}</button></div></header>
    <div class="mt-4 flex items-center gap-2.5 rounded-xl border border-amber-200/80 bg-amber-50/70 px-4 py-2.5">
      <Icon name="alert" :size="18" class="shrink-0 text-amber-600" /><p class="text-sm leading-6 text-amber-900"><strong class="font-semibold">保存即生效，包含已有用户。</strong> 已用量和预占时长保留；降低额度后，剩余额度最低为 0，不重置使用记录。</p>
    </div>
    <p v-if="!adminAuth.isSuperadmin" class="mt-2 text-xs text-slate-500">当前为只读模式，只有超级管理员可以修改额度。</p>
    <p v-if="notice" role="status" class="mt-2 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-800"><Icon name="check" :size="18" />{{ notice }}</p>
    <p v-if="error && !editing" role="alert" class="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{{ error }}</p>
    <p v-if="loading && !plans.length" role="status" class="py-12 text-center text-sm text-slate-500">正在加载套餐额度…</p>

    <div v-if="plans.length" class="admin-card mt-4 hidden overflow-hidden md:block">
      <table class="w-full table-fixed text-left">
        <thead><tr class="border-b border-slate-200"><th class="w-[29%] px-6 py-4 align-bottom text-xs font-medium text-slate-500">功能与计量方式</th><th v-for="plan in plans" :key="plan.code" class="px-5 py-4 align-top" :class="{ 'bg-indigo-50/40': plan.code === 'monthly' }">
          <span class="mr-2.5 inline-flex h-8 w-8 items-center justify-center rounded-xl align-middle" :class="plan.code === 'free' ? 'bg-slate-100 text-slate-600' : plan.code === 'monthly' ? 'bg-indigo-100 text-indigo-600' : 'bg-amber-100 text-amber-700'"><Icon :name="plan.code === 'free' ? 'user' : 'crown'" :size="17" /></span>
          <span class="align-middle text-base font-bold text-slate-900">{{ plan.name }}</span>
          <span class="mt-1 block text-xs font-normal text-slate-500">{{ plan.code === 'free' ? '基础使用额度' : plan.code === 'monthly' ? '按月订阅额度' : '年卡每月发放' }}</span>
        </th></tr></thead>
        <tbody><tr v-for="field in fields" :key="field.key" class="border-b border-slate-100 last:border-0"><th class="px-6 py-3.5 font-normal"><span class="block text-sm font-semibold text-slate-700">{{ field.label }}</span><span class="mt-0.5 block text-xs text-slate-500">{{ field.unit }}</span></th><td v-for="plan in plans" :key="plan.code" class="px-5 py-3.5" :class="{ 'bg-indigo-50/40': plan.code === 'monthly' }"><span class="text-base font-bold tabular-nums" :class="plan.code === 'monthly' ? 'text-indigo-700' : 'text-slate-800'">{{ valueLabel(plan, field) }}</span></td></tr></tbody>
        <tfoot v-if="adminAuth.isSuperadmin"><tr class="border-t border-slate-200"><td class="px-6 py-3.5 text-xs leading-5 text-slate-500">每次编辑一个套餐，确认后统一保存</td><td v-for="plan in plans" :key="plan.code" class="px-5 py-3.5" :class="{ 'bg-indigo-50/40': plan.code === 'monthly' }"><button class="min-h-10 w-full rounded-xl border border-indigo-200 bg-white px-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50" @click="edit(plan)">编辑{{ plan.name.replace('会员', '') }}额度</button></td></tr></tfoot>
      </table>
    </div>

    <div v-if="plans.length" class="mt-6 md:hidden">
      <div class="grid grid-cols-3 gap-1 rounded-xl bg-slate-200/60 p-1" role="group" aria-label="选择套餐">
        <button v-for="plan in plans" :key="plan.code" class="min-h-11 rounded-lg text-sm font-semibold" :class="selected === plan.code ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500'" :aria-pressed="selected === plan.code" @click="selected = plan.code">{{ plan.name }}</button>
      </div>
      <article v-if="active" class="mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div class="flex items-center justify-between border-b border-slate-100 px-5 py-5"><h2 class="text-lg font-bold">{{ active.name }}</h2><span class="rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-600">当前生效额度</span></div>
        <dl class="px-5"><div v-for="field in fields" :key="field.key" class="flex items-center justify-between gap-3 border-b border-slate-100 py-4 last:border-0"><dt class="text-sm font-medium text-slate-600">{{ field.label }}<span class="mt-1 block text-xs font-normal text-slate-500">{{ field.unit }}</span></dt><dd class="shrink-0 text-lg font-bold tabular-nums text-slate-900">{{ valueLabel(active, field) }}</dd></div></dl>
        <div v-if="adminAuth.isSuperadmin" class="border-t border-slate-100 p-5"><button class="btn-primary min-h-12 w-full rounded-xl text-sm font-bold" @click="edit(active)">编辑{{ active.name.replace('会员', '') }}额度</button></div>
      </article>
    </div>
    <div class="mt-5 flex flex-wrap items-start justify-between gap-3 text-xs leading-6 text-slate-500"><p>批量提取与单条识别不能超过系统上限，编辑时会标明可用范围。</p><RouterLink to="/admin/pricing" class="inline-flex min-h-8 items-center gap-1 font-medium text-indigo-600">修改会员价格 <Icon name="chevron" :size="14" /></RouterLink></div>

    <AdminDialog v-if="editing" :title="confirming ? '确认额度变更' : `编辑${editing.name}额度`" wide :busy="saving" @close="editing = null">
      <form @submit.prevent="confirming ? save() : review()">
        <template v-if="!confirming">
          <p class="mb-5 text-sm leading-6 text-slate-500">填写新的额度。右侧注明当前值，便于对照；所有项目均使用整数。</p>
          <div class="grid gap-x-6 gap-y-5 sm:grid-cols-2"><div v-for="field in fields" :key="field.key">
            <label :for="`limit-${field.key}`" class="mb-2 flex flex-wrap items-center justify-between gap-1 text-sm font-semibold text-slate-800"><span>{{ field.label }}</span><span class="text-xs font-normal text-slate-500">当前 {{ valueOf(editing, field) }}</span></label>
            <div class="flex min-h-12 overflow-hidden rounded-xl border bg-white focus-within:ring-2 focus-within:ring-indigo-100" :class="errors[field.key] ? 'border-rose-400' : 'border-slate-200 focus-within:border-indigo-400'"><input :id="`limit-${field.key}`" v-model="draft[field.key]" inputmode="numeric" maxlength="7" :aria-invalid="!!errors[field.key]" :aria-describedby="`hint-${field.key}`" class="min-w-0 flex-1 bg-transparent px-3 py-3 text-base font-semibold tabular-nums text-slate-900 outline-none" @blur="validate(field)" /><span class="flex shrink-0 items-center bg-slate-50 px-3 text-xs text-slate-500">{{ field.unit.split(' / ')[0] }}</span></div>
            <p :id="`hint-${field.key}`" class="mt-1.5 text-xs leading-5" :class="errors[field.key] ? 'text-rose-600' : 'text-slate-500'">{{ errors[field.key] || `${field.hint} · 1–${field.max}` }}</p>
          </div></div>
        </template>
        <template v-else>
          <p class="mb-4 text-sm text-slate-500">{{ editing.name }} · 本次修改 {{ changes.length }} 项额度</p>
          <dl class="overflow-hidden rounded-xl border border-slate-200"><div v-for="field in changes" :key="field.key" class="grid grid-cols-[1fr_auto] items-center gap-3 border-b border-slate-100 px-4 py-4 last:border-0"><dt class="text-sm font-medium text-slate-700">{{ field.label }}<span class="mt-1 block text-xs font-normal text-slate-500">{{ field.unit }}</span></dt><dd class="flex items-center gap-2 text-base font-bold tabular-nums"><span class="font-normal text-slate-500">{{ valueOf(editing, field) }}</span><span class="text-slate-300">→</span><span :class="Number(draft[field.key]) < valueOf(editing, field) ? 'text-amber-700' : 'text-indigo-700'">{{ draft[field.key] }}</span></dd></div></dl>
          <p class="mt-4 rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">确认后立即影响{{ editing.name }}的已有用户。已使用和预占额度不会清零，降低额度可能让部分用户暂时无法提交新任务。</p>
        </template>
        <p v-if="error" role="alert" class="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ error }}</p>
        <div class="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-5"><button type="button" :disabled="saving" class="min-h-11 rounded-lg px-3 text-sm font-semibold text-slate-500" @click="confirming ? confirming = false : editing = null">{{ confirming ? '返回修改' : '取消' }}</button><button :disabled="saving" class="btn-primary min-h-12 rounded-xl px-6 text-sm font-bold">{{ saving ? '保存中…' : confirming ? '确认保存并立即生效' : `核对 ${changes.length} 项修改` }}</button></div>
      </form>
    </AdminDialog>
  </section>
</template>
