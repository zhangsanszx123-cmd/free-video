<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import FormField from '../components/FormField.vue'
import Icon from '../components/Icon.vue'
import UserAvatar from '../components/UserAvatar.vue'
import QuotaCard from '../components/QuotaCard.vue'
import { membership } from '../membership.js'
import { account, accountApi, rules } from '../account.js'
import { orderStatusLabel } from '../payment.js'
import { useRoute } from 'vue-router'

let disposed = false
onUnmounted(() => { disposed = true })

const user = computed(() => account.user)
const displayName = computed(() => user.value?.nickname || user.value?.username || '')
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '')
const toast = ref('')
let toastTimer
function notify(message) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3000)
}
onUnmounted(() => clearTimeout(toastTimer))

const route = useRoute()
const sections = [
  { id: 'membership', label: '会员与额度', icon: 'crown', description: '查看每月语音识别用量与会员权益' },
  { id: 'profile', label: '基本资料', icon: 'user', description: '管理你的账号资料' },
  { id: 'password', label: '账号安全', icon: 'shield', description: '更新密码，保护账号安全' },
  { id: 'devices', label: '登录设备', icon: 'monitor', description: '查看和管理登录会话' },
  { id: 'delete', label: '注销账号', icon: 'trash', description: '永久删除账号' },
]
const active = ref(sections.some(item => item.id === route.query.section) ? route.query.section : 'profile')

/* Orders */
const orders = reactive({ list: [], loading: false, error: '' })
async function loadOrders() {
  if (orders.loading) return
  orders.loading = true
  orders.error = ''
  try {
    const { orders: list } = await accountApi.orders()
    if (!disposed) orders.list = list
  } catch (e) {
    if (!disposed) orders.error = e.message
  } finally {
    orders.loading = false
  }
}
onMounted(loadOrders)
const deleteExpanded = ref(false)
function cancelProfile() {
  nickname.value = user.value?.nickname || ''
  profile.error = ''
}
watch(() => user.value?.nickname, (now, before) => {
  if (nickname.value === before) nickname.value = now || ''
})
watch(active, () => {
  deleteExpanded.value = false
  Object.assign(del, { password: '', confirm: '', error: '' })
  Object.assign(pwd, { old: '', next: '', confirm: '', error: '', oldError: '', nextError: '', confirmError: '' })
})
/* Profile */
const nickname = ref(user.value?.nickname || '')
const profile = reactive({ saving: false, error: '' })
const nicknameChanged = computed(() => nickname.value.trim() !== (user.value?.nickname || ''))
async function saveProfile() {
  if (profile.saving || !nicknameChanged.value) return
  profile.error = rules.nickname(nickname.value)
  if (profile.error) return
  profile.saving = true
  try {
    const { user: updated } = await accountApi.updateProfile({ nickname: nickname.value.trim() })
    if (disposed) return
    account.updateUser(updated)
    nickname.value = updated.nickname
    notify('昵称已更新')
  } catch (e) {
    if (!disposed) profile.error = e.message
  } finally {
    profile.saving = false
  }
}

/* Password */
const pwd = reactive({ old: '', next: '', confirm: '', saving: false, error: '', oldError: '', nextError: '', confirmError: '' })
async function changePassword() {
  if (pwd.saving) return
  pwd.error = ''
  pwd.oldError = !pwd.old ? '请输入当前密码' : ''
  pwd.nextError = rules.password(pwd.next, user.value?.username) || (pwd.next === pwd.old ? '新密码不能与当前密码相同' : '')
  pwd.confirmError = pwd.confirm !== pwd.next ? '两次输入的新密码不一致' : ''
  if (pwd.oldError || pwd.nextError || pwd.confirmError) return
  pwd.saving = true
  try {
    await accountApi.changePassword({ old_password: pwd.old, new_password: pwd.next })
    account.markLoggedOut('password_changed')
  } catch (e) {
    if (!disposed) pwd.error = e.message
  } finally {
    pwd.saving = false
  }
}

/* Devices */
let sessionLoading = false
const devices = reactive({ list: [], loading: true, error: '', busy: '' })
async function loadSessions() {
  if (devices.busy || sessionLoading) return
  sessionLoading = true
  devices.loading = true
  devices.error = ''
  try {
    const { sessions } = await accountApi.sessions()
    if (!disposed) devices.list = sessions.sort((a, b) => Number(b.current) - Number(a.current))
  } catch (e) {
    if (!disposed) devices.error = e.message
  } finally {
    sessionLoading = false
    devices.loading = false
  }
}
async function revoke(session) {
  if (devices.busy || devices.loading) return
  devices.error = ''
  devices.busy = session.id
  try {
    await accountApi.revokeSession(session.id)
    if (disposed) return
    devices.list = devices.list.filter((s) => s.id !== session.id)
    notify('已下线该设备')
  } catch (e) {
    if (!disposed) devices.error = e.message
  } finally {
    devices.busy = ''
  }
}
async function revokeOthers() {
  if (devices.busy || devices.loading) return
  devices.error = ''
  devices.busy = 'others'
  try {
    const { revoked } = await accountApi.revokeOthers()
    if (disposed) return
    devices.list = devices.list.filter((s) => s.current)
    notify(revoked ? `已退出其它 ${revoked} 台设备` : '没有其它登录设备')
  } catch (e) {
    if (!disposed) devices.error = e.message
  } finally {
    devices.busy = ''
  }
}
const otherDevices = computed(() => devices.list.filter((s) => !s.current).length)
onMounted(loadSessions)

/* Delete account */
const del = reactive({ password: '', confirm: '', saving: false, error: '' })
const deleteReady = computed(() => del.password && del.confirm.toLowerCase() === (user.value?.username || '').toLowerCase())
async function deleteAccount() {
  if (del.saving || !deleteReady.value) return
  del.error = ''
  del.saving = true
  try {
    await accountApi.deleteAccount({ password: del.password, confirm_username: del.confirm })
    account.markLoggedOut('deleted')
  } catch (e) {
    if (!disposed) del.error = e.message
  } finally {
    del.saving = false
  }
}
</script>

<template>
  <section v-if="user" class="hero-bg min-h-[calc(100dvh-4rem)] px-4 py-8 sm:py-12">
    <div class="mx-auto max-w-6xl space-y-6">
      <header class="glass-card flex flex-col items-start gap-4 rounded-3xl p-6 sm:flex-row sm:items-center sm:p-8">
        <UserAvatar :name="displayName" :size="64" />
        <div class="min-w-0 flex-1">
          <p class="mb-2 text-sm font-semibold text-indigo-600">个人中心</p>
          <h1 class="break-words [overflow-wrap:anywhere] text-2xl font-extrabold tracking-tight text-slate-950">{{ displayName }}</h1>
          <p class="mt-1 break-words text-sm text-slate-500">用户名 @{{ user.username }} · 注册于 {{ fmtTime(user.created_at) }}</p>
        </div>
        <span class="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 ring-1 ring-amber-200">
          <Icon name="crown" :size="14" /> {{ membership.data?.name || '我的会员' }}
        </span>
      </header>

      <div class="grid items-start gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="个人中心分区" class="flex gap-2 overflow-x-auto rounded-2xl border border-slate-200 bg-white p-2 lg:sticky lg:top-24 lg:flex-col">
          <button v-for="item in sections" :key="item.id" type="button" :aria-current="active === item.id ? 'page' : undefined" :disabled="profile.saving || pwd.saving || del.saving"
            class="flex min-h-12 shrink-0 items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-semibold transition"
            :class="active === item.id ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-50'" @click="active = item.id">
            <Icon :name="item.icon" :size="18" />{{ item.label }}
          </button>
        </nav>
        <div class="min-w-0">
        <p class="mb-4 text-sm text-slate-500">{{ sections.find(item => item.id === active).description }}</p>
        <div v-show="active === 'membership'" class="space-y-4">
          <QuotaCard />
          <div class="flex flex-wrap gap-3">
            <RouterLink to="/history?status=active" class="btn-ghost flex min-h-11 items-center gap-2 px-4 text-sm font-semibold"><Icon name="clock" :size="18" />执行中任务</RouterLink>
            <RouterLink to="/history" class="btn-ghost flex min-h-11 items-center gap-2 px-4 text-sm font-semibold"><Icon name="file" :size="18" />历史任务</RouterLink>
          </div>
          <section class="glass-card rounded-3xl p-6 sm:p-8" aria-labelledby="orders-title">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <h2 id="orders-title" class="flex items-center gap-2 text-lg font-bold text-slate-900"><Icon name="clipboard" :size="18" class="text-indigo-600" /> 我的订单</h2>
              <button type="button" :disabled="orders.loading" class="btn-ghost min-h-11 px-4 text-sm font-semibold disabled:opacity-50" @click="loadOrders">{{ orders.loading ? '刷新中…' : '刷新订单' }}</button>
            </div>
            <p v-if="orders.error" role="alert" class="mt-4 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">{{ orders.error }}</p>
            <p v-else-if="!orders.loading && !orders.list.length" class="mt-4 text-sm text-slate-500">暂无订单。<RouterLink to="/pricing" class="font-semibold text-indigo-600 hover:underline">查看会员套餐</RouterLink></p>
            <ul class="mt-4 divide-y divide-slate-100">
              <li v-for="o in orders.list" :key="o.out_trade_no" class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2 font-semibold text-slate-800">
                    {{ o.plan_name }} · ¥{{ o.amount }}
                    <span class="rounded-md px-1.5 py-px text-xs font-bold" :class="o.status === 'paid' ? 'bg-emerald-50 text-emerald-600' : o.status === 'refund_required' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'">{{ orderStatusLabel(o) }}</span>
                  </div>
                  <div class="mt-1 break-all text-xs leading-6 text-slate-500">订单号 {{ o.out_trade_no }} · 下单 {{ fmtTime(o.created_at) }}<template v-if="o.paid_at"> · 支付 {{ fmtTime(o.paid_at) }}</template></div>
                </div>
                <RouterLink v-if="o.status === 'pending'" :to="`/pay/result?out_trade_no=${o.out_trade_no}`" class="min-h-11 self-start rounded-xl px-4 py-2.5 text-sm font-semibold text-indigo-600 hover:bg-indigo-50 sm:self-auto">我已付款，查询结果</RouterLink>
              </li>
            </ul>
          </section>
        </div>
        <section v-show="active === 'profile'" class="glass-card rounded-3xl p-6 sm:p-8" aria-labelledby="profile-title">
          <h2 id="profile-title" class="flex items-center gap-2 text-lg font-bold text-slate-900"><Icon name="user" :size="18" class="text-indigo-600" /> 基本资料</h2>
          <form class="mt-4 space-y-4" novalidate @submit.prevent="saveProfile">
            <FormField :model-value="user.username" label="用户名" icon="user" disabled hint="用户名用于登录，不可修改" />
            <FormField v-model="nickname" label="昵称" icon="edit" maxlength="30" autocomplete="nickname" :error="profile.error" :disabled="profile.saving" :hint="`${[...nickname].length} / 30 字符`" />
            <button type="submit" :disabled="profile.saving || !nicknameChanged" class="btn-primary flex min-h-11 w-full items-center justify-center rounded-xl font-bold">
              {{ profile.saving ? '保存中…' : '保存昵称' }}
            </button>
            <button type="button" :disabled="profile.saving || !nicknameChanged" class="btn-ghost min-h-11 w-full px-4 text-sm font-semibold disabled:opacity-50" @click="cancelProfile">取消修改</button>
          </form>
        </section>

        <section v-show="active === 'password'" class="glass-card rounded-3xl p-6 sm:p-8" aria-labelledby="password-title">
          <h2 id="password-title" class="flex items-center gap-2 text-lg font-bold text-slate-900"><Icon name="lock" :size="18" class="text-indigo-600" /> 修改密码</h2>
          <form class="mt-4 space-y-4" novalidate @submit.prevent="changePassword">
            <input type="text" :value="user.username" autocomplete="username" class="hidden" tabindex="-1" aria-hidden="true" readonly />
            <FormField v-model="pwd.old" label="当前密码" type="password" autocomplete="current-password" maxlength="128" :error="pwd.oldError" :disabled="pwd.saving" />
            <FormField v-model="pwd.next" label="新密码" type="password" autocomplete="new-password" maxlength="128" hint="8–128 个字符" :error="pwd.nextError" :disabled="pwd.saving" />
            <FormField v-model="pwd.confirm" label="确认新密码" type="password" autocomplete="new-password" maxlength="128" :error="pwd.confirmError" :disabled="pwd.saving" />
            <p v-if="pwd.error" role="alert" class="rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">{{ pwd.error }}</p>
            <p class="text-xs text-slate-500">修改成功后，所有设备（包括当前设备）都会退出登录。</p>
            <button type="submit" :disabled="pwd.saving" class="btn-primary flex min-h-11 w-full items-center justify-center rounded-xl font-bold">
              {{ pwd.saving ? '提交中…' : '修改密码' }}
            </button>
          </form>
        </section>
      <section v-show="active === 'devices'" class="glass-card rounded-3xl p-6 sm:p-8" aria-labelledby="devices-title">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 id="devices-title" class="flex items-center gap-2 text-lg font-bold text-slate-900"><Icon name="monitor" :size="18" class="text-indigo-600" /> 登录设备 <span v-if="!devices.loading" class="text-sm font-normal text-slate-500">{{ devices.list.length }} 台</span></h2>
          <button type="button" :disabled="devices.loading || Boolean(devices.busy)" class="btn-ghost min-h-11 px-4 text-sm font-semibold disabled:opacity-50" @click="loadSessions">{{ devices.loading ? '刷新中…' : '刷新设备' }}</button>
          <button type="button" :disabled="devices.loading || Boolean(devices.busy) || !otherDevices" class="btn-ghost min-h-11 px-4 text-sm font-semibold disabled:opacity-50" @click="revokeOthers">
            {{ devices.busy === 'others' ? '处理中…' : '退出其它所有设备' }}
          </button>
        </div>
        <p v-if="devices.error" role="alert" class="mt-4 flex items-center justify-between gap-3 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
          {{ devices.error }} <button type="button" :disabled="devices.loading || Boolean(devices.busy)" class="min-h-11 shrink-0 font-semibold hover:underline" @click="loadSessions">重新加载</button>
        </p>
        <p v-if="devices.loading" class="mt-4 text-sm text-slate-500">正在加载…</p>
        <p v-if="!devices.loading && !devices.error && !devices.list.length" class="mt-4 text-sm text-slate-500">暂无登录设备，请刷新重试。</p>
        <ul v-if="!devices.loading" class="mt-4 divide-y divide-slate-100">
          <li v-for="s in devices.list" :key="s.id" class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 font-semibold text-slate-800">
                {{ s.device }}
                <span v-if="s.current" class="rounded-md bg-emerald-50 px-1.5 py-px text-xs font-bold text-emerald-600">当前设备</span>
              </div>
              <div class="mt-1 break-words text-xs leading-6 text-slate-500">IP {{ s.ip || '未知' }} · 登录于 {{ fmtTime(s.created_at) }} · 最近活跃 {{ fmtTime(s.last_seen_at) }}</div>
            </div>
            <button v-if="!s.current" type="button" :disabled="Boolean(devices.busy)"
              class="min-h-11 self-start rounded-xl px-4 text-sm font-semibold text-rose-600 hover:bg-rose-50 disabled:opacity-50 sm:self-auto" @click="revoke(s)">
              {{ devices.busy === s.id ? '下线中…' : '下线' }}
            </button>
          </li>
        </ul>
        <p class="mt-2 text-xs text-slate-400">登录状态保持 7 天；不认识的设备请立即下线并修改密码。</p>
      </section>

      <section v-show="active === 'delete'" class="rounded-3xl border border-rose-200 bg-rose-50/60 p-6" aria-labelledby="delete-title">
        <h2 id="delete-title" class="flex items-center gap-2 text-lg font-bold text-rose-700"><Icon name="trash" :size="18" /> 注销账号</h2>
        <p class="mt-1 text-sm text-rose-600/90">注销后账号与所有登录设备将被永久删除，无法恢复；用户名可被重新注册。</p>
        <button v-if="!deleteExpanded" type="button" aria-expanded="false" aria-controls="delete-form" class="btn-ghost mt-5 min-h-11 px-5 font-semibold text-rose-700" @click="deleteExpanded = true">申请注销账号</button>
        <form v-if="deleteExpanded" id="delete-form" class="mt-4 grid gap-4 sm:grid-cols-2" novalidate @submit.prevent="deleteAccount">
          <FormField v-model="del.password" label="当前密码" type="password" autocomplete="current-password" maxlength="128" />
          <FormField v-model="del.confirm" label="输入用户名以确认" maxlength="32" :placeholder="user.username" />
          <p v-if="del.error" role="alert" class="rounded-xl bg-white px-3 py-2.5 text-sm text-rose-600 sm:col-span-2">{{ del.error }}</p>
          <button type="submit" :disabled="del.saving || !deleteReady"
            class="min-h-11 rounded-xl bg-rose-600 px-5 font-bold text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-2 sm:justify-self-start">
            {{ del.saving ? '注销中…' : '永久注销账号' }}
          </button>
          <button type="button" :disabled="del.saving" class="btn-ghost min-h-11 px-5 font-semibold" @click="deleteExpanded = false; del.password = ''; del.confirm = ''; del.error = ''">取消注销</button>
        </form>
      </section>
        </div>
      </div>
    </div>

    <div v-if="toast" role="status" class="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm text-white shadow-lg">{{ toast }}</div>
  </section>
</template>
