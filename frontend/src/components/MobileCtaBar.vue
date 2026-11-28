<script setup>
import { computed, onUnmounted, ref, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './Icon.vue'

const route = useRoute()
const hidden = ref(sessionStorage.getItem('fv-cta-hidden') === '1')
// route.name is undefined until the first (possibly auth-guarded) navigation resolves.
const visible = computed(() => !hidden.value && Boolean(route.name) && !['pricing', 'batch', 'login', 'register', 'account', 'history', 'apiKeys', 'apiDocs'].includes(route.name))
watchEffect(() => {
  document.documentElement.classList.toggle('mobile-cta-visible', visible.value)
})
onUnmounted(() => document.documentElement.classList.remove('mobile-cta-visible'))
function close() {
  hidden.value = true
  sessionStorage.setItem('fv-cta-hidden', '1')
}
</script>

<template>
  <div v-if="visible"
    class="fixed inset-x-3 bottom-3 z-40 flex items-center gap-3 rounded-2xl bg-slate-950/95 p-3 pl-4 text-white shadow-2xl backdrop-blur md:hidden"
    style="margin-bottom: env(safe-area-inset-bottom)">
    <Icon name="crown" class="shrink-0 text-amber-400" />
    <div class="min-w-0 flex-1">
      <div class="truncate text-sm font-bold">会员套餐 · 更多语音识别时长</div>
      <div class="truncate text-xs text-slate-400">游客可下载 2 个视频，AI 总结可体验 1 次</div>
    </div>
    <RouterLink to="/pricing" class="btn-gold shrink-0 rounded-xl px-3 py-2 text-sm font-bold">立即升级</RouterLink>
    <button class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-slate-300 hover:bg-white/10" aria-label="关闭升级提示" @click="close"><Icon name="x" :size="18" /></button>
  </div>
</template>
