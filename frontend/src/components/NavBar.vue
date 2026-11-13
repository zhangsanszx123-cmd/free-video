<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './Icon.vue'
import UserAvatar from './UserAvatar.vue'
import QuotaCard from './QuotaCard.vue'
import { loadMembership, membership } from '../membership.js'
import { account, openAuth } from '../account.js'

const open = ref(false)
const menuOpen = ref(false)
const loggingOut = ref(false)
const menuEl = ref(null)
const route = useRoute()
watch(() => route.fullPath, () => { open.value = false; menuOpen.value = false })

const links = [
  { to: '/', label: '视频下载', icon: 'download' },
  { to: '/learn', label: 'AI 总结', icon: 'sparkles', pro: true },
  { to: '/batch', label: '批量提取', icon: 'layers', pro: true },
  { to: '/pricing', label: '定价', icon: 'crown' },
]
function openDialog(tab) {
  open.value = false
  openAuth({ tab })
}
const displayName = computed(() => account.user?.nickname || account.user?.username || '')
const isPro = computed(() => ['monthly', 'yearly'].includes(membership.data?.plan))
const membershipLabel = computed(() => membership.data
  ? (isPro.value ? 'PRO 用户' : '普通用户')
  : (membership.error ? '身份暂不可用' : '身份加载中…'))
const membershipTone = computed(() => isPro.value
  ? 'bg-amber-50 text-amber-700 ring-amber-200'
  : 'bg-slate-100 text-slate-600 ring-slate-200')
watch(menuOpen, value => { if (value) loadMembership() })
watch(open, value => { if (value && account.loggedIn) loadMembership() })

async function logout() {
  if (loggingOut.value) return
  loggingOut.value = true
  try { await account.logout() } catch { /* local state is cleared even if the request failed */ } finally {
    loggingOut.value = false
    menuOpen.value = false
    open.value = false
  }
}
function onDocumentClick(event) {
  if (menuOpen.value && menuEl.value && !menuEl.value.contains(event.target)) menuOpen.value = false
}
function onKeydown(event) {
  if (event.key === 'Escape') menuOpen.value = false
}
onMounted(() => {
  account.ensure()
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <nav class="sticky top-0 z-50 h-16 w-full border-b border-slate-200/80 bg-white/85 backdrop-blur-xl">
    <div class="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
      <RouterLink to="/" class="flex min-w-0 items-center gap-2.5 transition hover:opacity-80">
        <img src="/logo.svg" alt="FreeVideo" class="h-8 w-8 shrink-0" />
        <div class="min-w-0">
          <div class="truncate text-lg font-extrabold tracking-tight text-slate-950">Free<span class="text-grad">Video</span></div>
          <div class="hidden truncate text-xs text-slate-500 lg:block">1800+ 平台高清视频一键下载 · 无水印 · AI 总结</div>
        </div>
      </RouterLink>

      <div class="hidden items-center gap-1 md:ml-auto md:mr-2 md:flex">
        <RouterLink v-for="l in links" :key="l.to" :to="l.to"
          class="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-indigo-50 hover:text-indigo-600"
          exact-active-class="!bg-indigo-50 !text-indigo-600">
          <Icon :name="l.icon" :size="16" /> {{ l.label }}
          <span v-if="l.pro" class="pro-badge">PRO</span>
        </RouterLink>
      </div>

      <div class="hidden items-center gap-2 md:flex">
        <div v-if="account.loggedIn" ref="menuEl" class="relative">
          <button type="button" class="flex items-center gap-2 rounded-xl py-1 pl-1 pr-2 text-sm font-medium text-slate-700 transition hover:bg-indigo-50"
            :aria-expanded="menuOpen" aria-haspopup="menu" aria-controls="account-menu" @click="menuOpen = !menuOpen">
            <UserAvatar :name="displayName" :size="32" />
            <span class="max-w-28 truncate">{{ displayName }}</span>
            <Icon name="chevron" :size="14" class="text-slate-400 transition" :class="menuOpen ? 'rotate-180' : ''" />
          </button>
          <div v-if="menuOpen" id="account-menu" role="menu"
            class="absolute right-0 top-12 max-h-[calc(100dvh-6rem)] w-80 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
            <RouterLink to="/account" role="menuitem" :aria-label="`${displayName}，个人中心`"
              class="mb-2 flex min-h-16 items-center gap-3 rounded-xl bg-indigo-50/60 px-3 py-3 transition hover:bg-indigo-100/70 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
              @click="menuOpen = false">
              <UserAvatar :name="displayName" :size="40" />
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm font-bold text-slate-900">{{ displayName }}</div>
                <span class="mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset" :class="membershipTone">
                  <Icon v-if="isPro" name="crown" :size="12" />{{ membershipLabel }}
                </span>
              </div>
              <Icon name="chevron" :size="16" class="-rotate-90 text-indigo-500" />
            </RouterLink>
            <QuotaCard compact class="mb-2" />
            <RouterLink to="/history?status=active" role="menuitem" class="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm text-slate-700 hover:bg-indigo-50"><Icon name="clock" :size="16" />执行中任务</RouterLink>
            <RouterLink to="/history" role="menuitem" class="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm text-slate-700 hover:bg-indigo-50"><Icon name="file" :size="16" />历史任务</RouterLink>
            <RouterLink to="/account" role="menuitem" class="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm text-slate-700 hover:bg-indigo-50 hover:text-indigo-600">
              <Icon name="user" :size="16" /> 个人中心
            </RouterLink>
            <button type="button" role="menuitem" :disabled="loggingOut" class="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-sm text-slate-700 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-60" @click="logout">
              <Icon name="logout" :size="16" /> {{ loggingOut ? '正在退出…' : '退出登录' }}
            </button>
          </div>
        </div>
        <template v-else-if="account.status !== 'unknown'">
          <button type="button" class="rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:text-indigo-600" @click="openDialog('login')">登录</button>
          <button type="button" class="btn-ghost px-3 py-2 text-sm font-semibold" @click="openDialog('register')">注册</button>
        </template>
        <RouterLink to="/pricing" class="btn-gold inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-bold">
          <Icon name="crown" :size="16" /> 升级 Pro
        </RouterLink>
      </div>

      <button class="flex h-11 w-11 items-center justify-center rounded-lg text-slate-700 hover:bg-indigo-50 md:hidden" :aria-label="open ? '关闭导航菜单' : '打开导航菜单'" :aria-expanded="open" aria-controls="mobile-navigation" @click="open = !open">
        <Icon :name="open ? 'x' : 'menu'" :size="22" />
      </button>
    </div>

    <Transition enter-from-class="opacity-0 -translate-y-2" leave-to-class="opacity-0 -translate-y-2"
      enter-active-class="transition duration-200" leave-active-class="transition duration-150">
      <div v-if="open" id="mobile-navigation" class="absolute inset-x-0 top-16 max-h-[calc(100dvh-4rem)] overflow-y-auto border-b border-slate-200 bg-white p-3 shadow-xl md:hidden">
        <RouterLink v-if="account.loggedIn" to="/account" :aria-label="`${displayName}，个人中心`"
          class="mb-2 flex min-h-16 items-center gap-3 rounded-xl bg-indigo-50/60 px-3 py-3 transition hover:bg-indigo-100/70 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
          @click="open = false">
          <UserAvatar :name="displayName" :size="40" />
          <div class="min-w-0 flex-1">
            <div class="truncate font-bold text-slate-900">{{ displayName }}</div>
            <span class="mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset" :class="membershipTone">
              <Icon v-if="isPro" name="crown" :size="12" />{{ membershipLabel }}
            </span>
          </div>
          <Icon name="chevron" :size="16" class="-rotate-90 text-indigo-500" />
        </RouterLink>
        <div v-else-if="account.status !== 'unknown'" class="mb-2 grid grid-cols-2 gap-2">
          <button type="button" class="btn-ghost flex min-h-11 items-center justify-center font-semibold" @click="openDialog('login')">登录</button>
          <button type="button" class="btn-primary flex min-h-11 items-center justify-center rounded-xl font-semibold" @click="openDialog('register')">免费注册</button>
        </div>
        <template v-if="account.loggedIn">
          <QuotaCard compact class="mb-2" />
          <RouterLink to="/history?status=active" class="flex min-h-11 items-center gap-3 rounded-xl px-3 py-3 font-medium text-slate-800 hover:bg-indigo-50"><Icon name="clock" :size="18" />执行中任务</RouterLink>
          <RouterLink to="/history" class="flex min-h-11 items-center gap-3 rounded-xl px-3 py-3 font-medium text-slate-800 hover:bg-indigo-50"><Icon name="file" :size="18" />历史任务</RouterLink>
        </template>
        <RouterLink v-for="l in links" :key="l.to" :to="l.to"
          class="flex items-center gap-3 rounded-xl px-3 py-3 text-base font-medium text-slate-800 hover:bg-indigo-50"
          exact-active-class="!bg-indigo-50 !text-indigo-700">
          <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><Icon :name="l.icon" :size="18" /></span>
          {{ l.label }} <span v-if="l.pro" class="pro-badge">PRO</span>
        </RouterLink>
        <button v-if="account.loggedIn" type="button" :disabled="loggingOut"
          class="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-base font-medium text-slate-800 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-60" @click="logout">
          <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-rose-50 text-rose-500"><Icon name="logout" :size="18" /></span>
          {{ loggingOut ? '正在退出…' : '退出登录' }}
        </button>
        <RouterLink to="/pricing" class="btn-gold mt-2 flex items-center justify-center gap-2 rounded-xl py-3 font-bold">
          <Icon name="crown" :size="18" /> 查看会员套餐
        </RouterLink>
      </div>
    </Transition>
  </nav>
</template>
