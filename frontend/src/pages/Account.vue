<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import FormField from '../components/FormField.vue'
import Icon from '../components/Icon.vue'
import UserAvatar from '../components/UserAvatar.vue'
import { account, accountApi, rules } from '../account.js'

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
const pwd = reactive({ old: '', next: '', confirm: '', saving: false, error: '', fieldError: '' })
async function changePassword() {
  if (pwd.saving) return
  pwd.error = ''
  pwd.fieldError = !pwd.old ? '请输入当前密码' : rules.password(pwd.next, user.value?.username)
    || (pwd.next === pwd.old ? '新密码不能与当前密码相同' : '') || (pwd.confirm !== pwd.next ? '两次输入的新密码不一致' : '')
  if (pwd.fieldError) return
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
const devices = reactive({ list: [], loading: true, error: '', busy: '' })
async function loadSessions() {
  devices.loading = true
  devices.error = ''
  try {
    const { sessions } = await accountApi.sessions()
    if (!disposed) devices.list = sessions
  } catch (e) {
    if (!disposed) devices.error = e.message
  } finally {
    devices.loading = false
  }
}
async function revoke(session) {
  if (devices.busy) return
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
  if (devices.busy) return
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
    <div class="mx-auto max-w-4xl space-y-6">
      <header class="glass-card flex flex-col items-start gap-4 rounded-3xl p-6 sm:flex-row sm:items-center sm:p-8">
        <UserAvatar :name="displayName" :size="64" />
        <div class="min-w-0 flex-1">
          <h1 class="truncate text-2xl font-extrabold tracking-tight text-slate-950">{{ displayName }}</h1>
          <p class="mt-1 text-sm text-slate-500">用户名 @{{ user.username }} · 注册于 {{ fmtTime(user.created_at) }}</p>
        </div>
        <span class="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 ring-1 ring-amber-200">
          <Icon name="gift" :size="14" /> 演示版 · PRO 功能免费体验中
        </span>
      </header>

      <div class="grid gap-6 lg:grid-cols-2">
        <section class="glass-card rounded-3xl p-6" aria-labelledby="profile-title">
          <h2 id="profile-title" class="flex items-center gap-2 text-lg font-bold text-slate-900"><Icon name="user" :size="18" class="text-indigo-600" /> 基本资料</h2>
          <form class="mt-4 space-y-4" novalidate @submit.prevent="saveProfile">
            <FormField :model-value="user.username" label="用户名" icon="user" disabled hint="用户名用于登录，不可修改" />
            <FormField v-model="nickname" label="昵称" icon="edit" maxlength="30" autocomplete="nickname" :error="profile.error" />
            <button type="submit" :disabled="profile.saving || !nicknameChanged" class="btn-primary flex min-h-11 w-full items-center justify-center rounded-xl font-bold">
              {{ profile.saving ? '保存中…' : '保存昵称' }}
            </button>
          </form>
        </section>

        <section class="glass-card rounded-3xl p-6" aria-labelledby="password-title">
          <h2 id="password-title" class="flex items-center gap-2 text-lg font-bold text-slate-900"><Icon name="lock" :size="18" class="text-indigo-600" /> 修改密码</h2>
          <form class="mt-4 space-y-4" novalidate @submit.prevent="changePassword">
            <input type="text" :value="user.username" autocomplete="username" class="hidden" tabindex="-1" aria-hidden="true" readonly />
            <FormField v-model="pwd.old" label="当前密码" type="password" autocomplete="current-password" maxlength="128" />
            <FormField v-model="pwd.next" label="新密码" type="password" autocomplete="new-password" maxlength="128" hint="8–128 个字符" />
            <FormField v-model="pwd.confirm" label="确认新密码" type="password" autocomplete="new-password" maxlength="128" :error="pwd.fieldError" />
            <p v-if="pwd.error" role="alert" class="rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">{{ pwd.error }}</p>
            <p class="text-xs text-slate-500">修改成功后，所有设备（包括当前设备）都会退出登录。</p>
            <button type="submit" :disabled="pwd.saving" class="btn-primary flex min-h-11 w-full items-center justify-center rounded-xl font-bold">
              {{ pwd.saving ? '提交中…' : '修改密码' }}
            </button>
          </form>
        </section>
      </div>

      <section class="glass-card rounded-3xl p-6" aria-labelledby="devices-title">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 id="devices-title" class="flex items-center gap-2 text-lg font-bold text-slate-900"><Icon name="monitor" :size="18" class="text-indigo-600" /> 登录设备</h2>
          <button type="button" :disabled="Boolean(devices.busy) || !otherDevices" class="btn-ghost min-h-11 px-4 text-sm font-semibold disabled:opacity-50" @click="revokeOthers">
            {{ devices.busy === 'others' ? '处理中…' : '退出其它所有设备' }}
          </button>
        </div>
        <p v-if="devices.error" role="alert" class="mt-4 flex items-center justify-between gap-3 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-600">
          {{ devices.error }} <button type="button" class="shrink-0 font-semibold hover:underline" @click="loadSessions">重新加载</button>
        </p>
        <p v-if="devices.loading" class="mt-4 text-sm text-slate-500">正在加载…</p>
        <ul v-else class="mt-4 divide-y divide-slate-100">
          <li v-for="s in devices.list" :key="s.id" class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 font-semibold text-slate-800">
                {{ s.device }}
                <span v-if="s.current" class="rounded-md bg-emerald-50 px-1.5 py-px text-xs font-bold text-emerald-600">当前设备</span>
              </div>
              <div class="mt-0.5 text-xs text-slate-500">IP {{ s.ip || '未知' }} · 登录于 {{ fmtTime(s.created_at) }} · 最近活跃 {{ fmtTime(s.last_seen_at) }}</div>
            </div>
            <button v-if="!s.current" type="button" :disabled="Boolean(devices.busy)"
              class="min-h-11 self-start rounded-xl px-4 text-sm font-semibold text-rose-600 hover:bg-rose-50 disabled:opacity-50 sm:self-auto" @click="revoke(s)">
              {{ devices.busy === s.id ? '下线中…' : '下线' }}
            </button>
          </li>
        </ul>
        <p class="mt-2 text-xs text-slate-400">登录状态保持 7 天；不认识的设备请立即下线并修改密码。</p>
      </section>

      <section class="rounded-3xl border border-rose-200 bg-rose-50/60 p-6" aria-labelledby="delete-title">
        <h2 id="delete-title" class="flex items-center gap-2 text-lg font-bold text-rose-700"><Icon name="trash" :size="18" /> 注销账号</h2>
        <p class="mt-1 text-sm text-rose-600/90">注销后账号与所有登录设备将被永久删除，无法恢复；用户名可被重新注册。</p>
        <form class="mt-4 grid gap-4 sm:grid-cols-2" novalidate @submit.prevent="deleteAccount">
          <FormField v-model="del.password" label="当前密码" type="password" autocomplete="current-password" maxlength="128" />
          <FormField v-model="del.confirm" label="输入用户名以确认" maxlength="32" :placeholder="user.username" />
          <p v-if="del.error" role="alert" class="rounded-xl bg-white px-3 py-2.5 text-sm text-rose-600 sm:col-span-2">{{ del.error }}</p>
          <button type="submit" :disabled="del.saving || !deleteReady"
            class="min-h-11 rounded-xl bg-rose-600 px-5 font-bold text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-2 sm:justify-self-start">
            {{ del.saving ? '注销中…' : '永久注销账号' }}
          </button>
        </form>
      </section>
    </div>

    <div v-if="toast" role="status" class="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm text-white shadow-lg">{{ toast }}</div>
  </section>
</template>
