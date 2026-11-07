<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './Icon.vue'

const route = useRoute()
const hidden = ref(sessionStorage.getItem('fv-cta-hidden') === '1')
function close() {
  hidden.value = true
  sessionStorage.setItem('fv-cta-hidden', '1')
}
</script>

<template>
  <div v-if="!hidden && route.name !== 'pricing'"
    class="fixed inset-x-3 bottom-3 z-40 flex items-center gap-3 rounded-2xl bg-slate-950/95 p-3 pl-4 text-white shadow-2xl backdrop-blur md:hidden"
    style="margin-bottom: env(safe-area-inset-bottom)">
    <Icon name="crown" class="shrink-0 text-amber-400" />
    <div class="min-w-0 flex-1">
      <div class="truncate text-sm font-bold">Pro 会员 · 4K / 批量 / AI 全解锁</div>
      <div class="truncate text-xs text-slate-400">限时 5 折，低至 ¥0.27/天</div>
    </div>
    <RouterLink to="/pricing" class="btn-gold shrink-0 rounded-xl px-3 py-2 text-sm font-bold">立即升级</RouterLink>
    <button class="shrink-0 p-1 text-slate-400" aria-label="关闭" @click="close"><Icon name="x" :size="16" /></button>
  </div>
</template>
