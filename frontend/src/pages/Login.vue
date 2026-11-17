<script setup>
// Backup full-page login (the primary entry is the AuthModal dialog).
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import LoginForm from '../components/LoginForm.vue'
import { safeRedirect } from '../account.js'

const route = useRoute()
const router = useRouter()
const redirect = computed(() => safeRedirect(route.query.redirect))
const notice = computed(() => (route.query.redirect ? '请先登录后使用该功能' : ''))
const toRegister = (email) => router.replace({ name: 'register', query: { ...(route.query.redirect ? { redirect: redirect.value } : {}), ...(email ? { email } : {}) } })
</script>

<template>
  <AuthShell title="欢迎回来" subtitle="登录后可使用批量提取、AI 总结与个人中心">
    <LoginForm :notice="notice" autofocus @success="router.replace(redirect)" @switch="toRegister" />
  </AuthShell>
</template>
