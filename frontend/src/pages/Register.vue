<script setup>
// Backup full-page registration (the primary entry is the AuthModal dialog).
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import RegisterForm from '../components/RegisterForm.vue'
import { safeRedirect } from '../account.js'

const route = useRoute()
const router = useRouter()
const redirect = computed(() => safeRedirect(route.query.redirect))
const toLogin = () => router.replace({ name: 'login', query: route.query.redirect ? { redirect: redirect.value } : {} })
</script>

<template>
  <AuthShell title="创建账号" subtitle="仅需用户名和密码，注册后自动登录">
    <RegisterForm autofocus @success="router.replace(redirect)" @switch="toLogin" />
  </AuthShell>
</template>
