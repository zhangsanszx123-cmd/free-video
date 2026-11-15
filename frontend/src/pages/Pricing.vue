<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import FaqList from '../components/FaqList.vue'
import PayModal from '../components/PayModal.vue'
import { account, accountApi, openAuth } from '../account.js'
import { durationLabel, loadMembership, membership } from '../membership.js'
import { purchaseKind } from '../payment.js'
import { ui } from '../store.js'

const plans = ref([])
const paymentEnabled = ref(false)
const error = ref('')
const loading = ref(false)
const paying = ref(null)
async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await accountApi.plans()
    plans.value = data.plans
    paymentEnabled.value = data.payment_enabled
  } catch (e) { error.value = e.message }
  finally { loading.value = false }
}
onMounted(() => { load(); account.ensure().then(() => loadMembership()) })
watch(() => account.user?.id, (id) => { if (id) loadMembership() })

const limitItems = (plan) => (plan.ai_monthly_limit === undefined ? [] : [
  `AI 视频总结每月 ${plan.ai_monthly_limit} 个视频`,
  `AI 追问每天 ${plan.chat_daily_limit} 条`,
  `批量提取单次最多 ${plan.batch_max_links} 条链接`,
  `单条语音识别最长 ${plan.asr_max_minutes} 分钟`,
])
const limitRows = [
  ['AI 视频总结（每月）', (p) => `${p.ai_monthly_limit} 个视频`],
  ['AI 追问（每天）', (p) => `${p.chat_daily_limit} 条`],
  ['批量提取（单次）', (p) => `${p.batch_max_links} 条链接`],
  ['单条识别最长', (p) => `${p.asr_max_minutes} 分钟`],
]
const kindOf = (code) => (account.loggedIn ? purchaseKind(membership.data, code) : 'new')
const buttonLabel = (plan) => ({ new: '开通', renew: '续费', upgrade: '升级', refused: '开通' }[kindOf(plan.code)]
  + (plan.code === 'monthly' ? '月卡' : '年卡'))
const busyMembership = computed(() => account.loggedIn && !membership.data && !membership.error)

async function buy(plan) {
  if (!paymentEnabled.value) return ui.openUpgrade('会员在线支付')
  if (!account.loggedIn) {
    return openAuth({ notice: '登录后即可开通会员', onSuccess: () => buy(plan) })
  }
  await loadMembership()
  if (membership.error) return ui.notify(membership.error)
  if (kindOf(plan.code) !== 'refused') paying.value = plan
}
const faqs = computed(() => [
  { q: '不登录可以用吗？', a: '游客可免费解析并下载 2 个视频（含 MP3），字幕提取、语音识别、批量提取、AI 总结都需要登录。这 2 个视频的时长会在首次登录或注册后计入当月语音识别额度；登录后下载不限次数。' },
  { q: '什么操作会扣时长？', a: '仅语音识别扣时长，按服务端核实的音频时长计算，整秒向上取整。视频下载、提取平台现成字幕、复制和导出已有文稿均不扣识别时长。' },
  { q: '额度什么时候重置？', a: '免费用户从注册时间起，Pro 用户从开通时间起，每月同日同一时间重置（北京时间）。遇到当月没有的日期按月底处理，后续月份仍按最初日期计算。未用完的时长不结转，年卡按月发放额度。' },
  { q: 'Pro 会叠加免费额度吗？', a: '不叠加。账号只使用当前套餐标注的一套额度。首次开通立即开始新的 Pro 周期，免费剩余额度不转入；会员到期后按注册周期恢复免费套餐。' },
  paymentEnabled.value
    ? { q: '如何购买？支付后多久生效？', a: '登录后点击开通，跳转支付宝收银台付款，完成后自动返回本站并开通会员，通常几秒内生效。如果页面提示确认中，可稍后在个人中心「会员与额度」查看订单状态，同一笔付款不会重复开通或重复扣费。' }
    : { q: '现在可以在线购买吗？', a: '在线支付暂未开放，会员开通由管理员处理。本页价格与额度由服务端套餐配置提供。' },
  { q: '可以续费或升级吗？', a: '同档续费延长有效期，不提前重置额度或改变原重置日期。月卡升级年卡立即提高本期额度上限，保留已用量、预占和原重置日期，月卡剩余有效期顺延到年卡之后。年卡有效期内不能购买月卡。' },
  { q: 'AI 次数和批量上限怎么计算？', a: 'AI 视频总结按「视频」计次：同一视频在同一周期内的总结（含三种视角）、思维导图、字幕翻译和追问共算 1 个视频，生成失败不扣；AI 追问另按北京时间每天的条数限制。批量提取的上限是单次提交的链接条数。AI 次数与语音识别额度使用同一个重置周期，单条语音识别的最长时长随套餐不同。' },
  { q: '任务和文稿能保存多久？', a: '任务记录及转录文本保存 30 天。视频与音频为临时文件，下载地址可能过期。' },
])
</script>

<template>
  <section class="hero-bg py-12 sm:py-16">
    <div class="mx-auto max-w-6xl px-4 sm:px-6">
      <header class="text-center">
        <div class="inline-flex items-center gap-2 rounded-full bg-rose-50 px-3 py-1 text-xs font-bold text-rose-600 ring-1 ring-rose-200"><Icon name="clock" :size="14" /> 按个人周期重置 · 北京时间</div>
        <h1 class="mt-4 text-3xl font-extrabold tracking-tight sm:text-5xl">选择适合你的 <span class="text-gold">Pro 方案</span></h1>
        <p class="mx-auto mt-4 max-w-2xl text-sm text-slate-600 sm:text-base">视频下载与平台字幕提取免费，按需选择语音识别时长。</p>
      </header>
      <p v-if="error" role="alert" class="mt-8 rounded-xl bg-rose-50 p-4 text-rose-700">{{ error }} <button type="button" class="min-h-11 px-4 font-bold" @click="load">重新加载</button></p>
      <p v-if="loading" role="status" class="mt-10 text-center text-slate-500">正在加载套餐…</p>
      <div v-else class="mt-10 grid items-stretch gap-5 lg:grid-cols-3">
        <article v-for="plan in plans" :key="plan.code" class="relative flex flex-col rounded-3xl p-6 sm:p-8" :class="plan.code === 'yearly' ? 'bg-slate-950 text-white shadow-2xl shadow-indigo-500/30 ring-2 ring-amber-400 lg:-my-3 lg:py-11' : 'glass-card'">
          <span v-if="plan.code === 'yearly'" class="btn-gold absolute -top-3.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full px-4 py-1 text-xs font-extrabold">推荐方案 · 按月发放</span>
          <h2 class="text-lg font-bold" :class="plan.code === 'yearly' ? 'text-amber-300' : 'text-slate-900'">{{ plan.code === 'free' ? '免费版' : plan.code === 'monthly' ? 'Pro 月卡' : 'Pro 年卡' }}</h2>
          <p class="mt-1 text-sm" :class="plan.code === 'yearly' ? 'text-slate-400' : 'text-slate-500'">{{ plan.code === 'free' ? '登录后即可使用' : plan.code === 'yearly' ? '学习、创作长期必备' : '短期集中下载、追课程' }}</p>
          <div class="mt-5 flex items-end gap-2"><span class="text-lg font-bold">¥</span><strong class="text-5xl font-extrabold tracking-tight">{{ Number((plan.price_cents / 100).toFixed(2)) }}</strong><span class="pb-1.5 text-sm" :class="plan.code === 'yearly' ? 'text-slate-400' : 'text-slate-500'">/ {{ plan.code === 'yearly' ? '年' : '月' }}</span></div>
          <div class="mt-5 rounded-2xl border px-4 py-4 sm:px-5" :class="plan.code === 'yearly' ? 'border-amber-400/30 bg-amber-400/10' : 'border-indigo-200/70 bg-indigo-50/80'">
            <p class="flex items-center gap-2 text-sm font-semibold" :class="plan.code === 'yearly' ? 'text-amber-200' : 'text-indigo-700'"><Icon name="clock" :size="17" />视频转文字时长</p>
            <p class="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1"><strong class="text-3xl font-extrabold tracking-tight sm:text-4xl" :class="plan.code === 'yearly' ? 'text-amber-300' : 'text-indigo-700'">{{ durationLabel(plan.monthly_seconds) }}</strong><span class="text-sm font-medium" :class="plan.code === 'yearly' ? 'text-amber-200/80' : 'text-indigo-600'">/ 月</span></p>
          </div>
          <ul class="mt-6 flex-1 space-y-3 text-sm"><li v-for="text in limitItems(plan)" :key="text" class="flex items-start gap-2"><Icon name="check" :size="16" class="mt-0.5 shrink-0" :class="plan.code === 'yearly' ? 'text-amber-400' : 'text-emerald-500'" />{{ text }}</li></ul>
          <RouterLink v-if="plan.code === 'free'" to="/account" class="mt-8 flex min-h-12 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-3.5 font-bold text-slate-600">查看我的额度</RouterLink>
          <button v-else type="button" class="mt-8 min-h-12 w-full rounded-xl px-4 py-3.5 font-bold disabled:cursor-not-allowed disabled:opacity-50" :class="plan.code === 'yearly' ? 'btn-gold' : 'btn-primary'"
            :disabled="paymentEnabled && (busyMembership || kindOf(plan.code) === 'refused')" @click="buy(plan)">{{ buttonLabel(plan) }}</button>
          <p v-if="plan.code !== 'free'" class="mt-3 text-center text-xs" :class="plan.code === 'yearly' ? 'text-slate-400' : 'text-slate-500'">
            {{ !paymentEnabled ? '在线支付暂未开放' : kindOf(plan.code) === 'refused' ? '年卡有效期内无需购买月卡' : kindOf(plan.code) === 'upgrade' ? '立即升级，月卡剩余时长顺延' : kindOf(plan.code) === 'renew' ? '到期时间自动顺延' : '支付宝付款 · 支付成功自动开通' }}
          </p>
        </article>
      </div>
      <div class="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-slate-500"><span class="flex items-center gap-1"><Icon name="shield" :size="14" class="text-emerald-500" />额度安全结算</span><span class="flex items-center gap-1"><Icon name="check" :size="14" class="text-emerald-500" />仅语音识别扣时长</span><span class="flex items-center gap-1"><Icon name="phone" :size="14" class="text-emerald-500" />手机电脑通用</span></div>
    </div>
  </section>
  <section class="bg-white py-14">
    <div class="mx-auto max-w-3xl px-4 sm:px-6">
      <h2 class="section-title text-center">免费版 vs Pro</h2>
      <div class="mt-8 overflow-x-auto rounded-2xl border border-slate-200">
        <table class="w-full text-center text-sm"><thead class="bg-slate-50 text-slate-500"><tr><th class="px-4 py-3 text-left">权益</th><th v-for="plan in plans" :key="plan.code" class="px-3 py-3" :class="plan.code === 'yearly' ? 'bg-amber-50 text-amber-700' : ''">{{ plan.name }}</th></tr></thead><tbody class="divide-y divide-slate-100"><tr><td class="px-4 py-3 text-left font-medium text-slate-800">每月语音识别</td><td v-for="plan in plans" :key="plan.code" class="px-3 py-3 font-bold" :class="plan.code === 'yearly' ? 'bg-amber-50/40 text-amber-700' : 'text-slate-600'">{{ durationLabel(plan.monthly_seconds) }}</td></tr><tr v-for="row in (plans[0]?.ai_monthly_limit === undefined ? [] : limitRows)" :key="row[0]"><td class="px-4 py-3 text-left font-medium text-slate-800">{{ row[0] }}</td><td v-for="plan in plans" :key="plan.code" class="px-3 py-3 font-bold" :class="plan.code === 'yearly' ? 'bg-amber-50/40 text-amber-700' : 'text-slate-600'">{{ row[1](plan) }}</td></tr><tr v-for="text in ['视频下载与平台字幕', '已有文稿导出', '30 天任务历史']" :key="text"><td class="px-4 py-3 text-left font-medium text-slate-800">{{ text }}</td><td v-for="plan in plans" :key="plan.code" class="px-3 py-3" :class="plan.code === 'yearly' ? 'bg-amber-50/40 font-bold text-amber-700' : 'text-slate-500'">支持</td></tr></tbody></table>
      </div>
      <h2 class="section-title mt-14 text-center">购买问题</h2><FaqList :items="faqs" class="mt-8" />
    </div>
  </section>
  <PayModal v-if="paying" :plan="paying" @close="paying = null" />
</template>
