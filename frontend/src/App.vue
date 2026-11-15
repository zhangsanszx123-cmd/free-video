<script setup>
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import NavBar from './components/NavBar.vue'
import SiteFooter from './components/SiteFooter.vue'
import MobileCtaBar from './components/MobileCtaBar.vue'
import UpgradeModal from './components/UpgradeModal.vue'
import AuthModal from './components/AuthModal.vue'
import { account, openAuth, safeRedirect } from './account.js'
import { ui } from './store.js'

const route = useRoute()
const router = useRouter()

const relogin = {
  password_changed: '密码已修改，所有设备已退出，请使用新密码重新登录',
  expired: '登录已过期，请重新登录',
}

// Identity changed (this tab, another tab, or a 401).
watch(() => account.user?.id ?? null, (now, before) => {
  const reason = account.logoutReason
  account.logoutReason = ''
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
</script>

<template>
  <div class="flex min-h-screen flex-col overflow-x-hidden">
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
