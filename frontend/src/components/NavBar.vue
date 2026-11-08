<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './Icon.vue'
import { ui } from '../store.js'

const open = ref(false)
const route = useRoute()
watch(() => route.fullPath, () => (open.value = false))

const links = [
  { to: '/', label: '视频下载', icon: 'download' },
  { to: '/batch', label: '批量下载', icon: 'layers', pro: true },
  { to: '/ai', label: 'AI 总结/翻译', icon: 'sparkles', pro: true },
  { to: '/learn', label: 'AI 学习工作台', icon: 'sparkles', pro: true },
  { to: '/pricing', label: '定价', icon: 'crown' },
]
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

      <div class="hidden items-center gap-1 md:flex">
        <RouterLink v-for="l in links" :key="l.to" :to="l.to"
          class="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-indigo-50 hover:text-indigo-600"
          exact-active-class="!bg-indigo-50 !text-indigo-600">
          <Icon :name="l.icon" :size="16" /> {{ l.label }}
          <span v-if="l.pro" class="pro-badge">PRO</span>
        </RouterLink>
      </div>

      <div class="hidden items-center gap-2 md:flex">
        <button class="rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:text-indigo-600" @click="ui.openUpgrade('登录')">登录</button>
        <RouterLink to="/pricing" class="btn-gold inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-bold">
          <Icon name="crown" :size="16" /> 升级 Pro
        </RouterLink>
      </div>

      <button class="rounded-lg p-2 text-slate-700 hover:bg-indigo-50 md:hidden" aria-label="打开导航菜单" @click="open = !open">
        <Icon :name="open ? 'x' : 'menu'" :size="22" />
      </button>
    </div>

    <Transition enter-from-class="opacity-0 -translate-y-2" leave-to-class="opacity-0 -translate-y-2"
      enter-active-class="transition duration-200" leave-active-class="transition duration-150">
      <div v-if="open" class="absolute inset-x-0 top-16 border-b border-slate-200 bg-white p-3 shadow-xl md:hidden">
        <RouterLink v-for="l in links" :key="l.to" :to="l.to"
          class="flex items-center gap-3 rounded-xl px-3 py-3 text-base font-medium text-slate-800 hover:bg-indigo-50"
          exact-active-class="!bg-indigo-50 !text-indigo-700">
          <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><Icon :name="l.icon" :size="18" /></span>
          {{ l.label }} <span v-if="l.pro" class="pro-badge">PRO</span>
        </RouterLink>
        <RouterLink to="/pricing" class="btn-gold mt-2 flex items-center justify-center gap-2 rounded-xl py-3 font-bold">
          <Icon name="crown" :size="18" /> 升级 Pro · 限时 5 折
        </RouterLink>
      </div>
    </Transition>
  </nav>
</template>
