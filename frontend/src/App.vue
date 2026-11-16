<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import NavBar from './components/NavBar.vue'
import SiteFooter from './components/SiteFooter.vue'
import MobileCtaBar from './components/MobileCtaBar.vue'
import UpgradeModal from './components/UpgradeModal.vue'
import AuthModal from './components/AuthModal.vue'
import { account, closeAuth, openAuth, safeRedirect } from './account.js'
import { adminAuth } from './admin/adminAuth.js'
import { ui } from './store.js'

const route = useRoute()
const router = useRouter()
const retryingAdmin = ref(false)
async function retryAdmin() {
  if (retryingAdmin.value) return
  retryingAdmin.value = true
  try { await adminAuth.refresh(true) }
  finally { retryingAdmin.value = false }
}

const relogin = {
  password_changed: '密码已修改，所有设备已退出，请使用新密码重新登录',
  expired: '登录已过期，请重新登录',
}

// Identity changed (this tab, another tab, or a 401).
watch(() => account.user?.id ?? null, (now, before) => {
  const reason = account.logoutReason
  account.logoutReason = ''
  if (route.meta.admin) return
  if (now !== null) {
    if (route.meta.guestOnly) router.replace(safeRedirect(route.query.redirect))
    return
  }
  if (before === null) return
  const protectedPage = route.meta.requiresAuth
  const back = protectedPage ? route.fullPath : ''
  if (protectedPage) router.replace('/')
  if (reason === 'deleted') ui.notify('账号已注销')
  else if (relogin[reason]) openAuth({ notice: relogin[reason], redirect: reason === 'expired' ? back : '' })
})
watch(() => route.meta.admin, value => { if (value) closeAuth() })
watch(() => [adminAuth.status, adminAuth.user?.role], () => {
  if (!route.meta.admin || route.name === 'adminLogin') return
  if (adminAuth.status === 'guest') router.replace({ name: 'adminLogin', query: { redirect: route.fullPath } })
  else if (adminAuth.loggedIn && route.meta.superadmin && !adminAuth.isSuperadmin) {
    adminAuth.notice = '后台权限已更新，当前账号无权管理后台账号'
    router.replace({ name: 'adminUsers' })
  }
})
</script>

<template>
  <template v-if="route.meta.admin">
    <RouterView v-if="route.name === 'adminLogin' || adminAuth.loggedIn" :key="route.name === 'adminLogin' ? 'admin-login' : `admin:${adminAuth.version}`" />
    <main v-else-if="adminAuth.status === 'error'" class="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <section class="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8" role="alert">
        <h1 class="text-xl font-bold text-slate-950">后台连接暂不可用</h1>
        <p class="mt-3 text-sm leading-6 text-slate-600">{{ adminAuth.error || '暂时无法确认后台登录状态，请稍后重试。' }}</p>
        <p class="mt-2 text-sm leading-6 text-slate-500">重试后将继续打开当前后台页面。</p>
        <button type="button" class="btn-primary mt-6 min-h-12 w-full rounded-xl font-bold" :disabled="retryingAdmin" @click="retryAdmin">{{ retryingAdmin ? '正在重试…' : '重试连接' }}</button>
      </section>
    </main>
    <main v-else class="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500" role="status">正在返回后台登录…</main>
  </template>
  <div v-else class="flex min-h-screen flex-col overflow-x-hidden">
    <NavBar />
    <main class="flex-1">
      <!-- Remount when a user's session ends or switches so their results, chats and polling are dropped. -->
      <RouterView :key="`${String(route.name)}:${['verifyEmail', 'resetPassword'].includes(route.name) ? 'email-link' : account.version}`" />
    </main>
    <SiteFooter />
    <MobileCtaBar />
    <UpgradeModal />
    <AuthModal />
    <div v-if="ui.toast" role="status" class="fixed bottom-24 left-1/2 z-[60] -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm text-white shadow-lg md:bottom-6">
      {{ ui.toast }}
    </div>
  </div>
</template>
