<script setup>
import Icon from '../../components/Icon.vue'
defineProps({ page: Number, pages: Number, total: Number, loading: Boolean })
defineEmits(['change'])
</script>
<template>
  <nav v-if="total" aria-label="列表分页" class="mt-2.5 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600 sm:text-sm"><span>共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页</span><div class="flex gap-2"><button class="btn-ghost flex min-h-9 items-center gap-1 px-3.5 text-xs font-medium shadow-sm disabled:opacity-40 sm:text-sm" :disabled="loading || page <= 1" @click="$emit('change', page - 1)"><Icon name="chevron" :size="14" class="rotate-90" />上一页</button><button class="btn-ghost flex min-h-9 items-center gap-1 px-3.5 text-xs font-medium shadow-sm disabled:opacity-40 sm:text-sm" :disabled="loading || page >= pages" @click="$emit('change', page + 1)">下一页<Icon name="chevron" :size="14" class="-rotate-90" /></button></div></nav>
</template>
