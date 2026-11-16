<script setup>
defineProps({ page: Number, pages: Number, total: Number, loading: Boolean })
defineEmits(['change'])
</script>
<template>
  <nav v-if="total" aria-label="列表分页" class="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600"><span>共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页</span><div class="flex gap-2"><button class="btn-ghost min-h-11 px-4 disabled:opacity-40" :disabled="loading || page <= 1" @click="$emit('change', page - 1)">上一页</button><button class="btn-ghost min-h-11 px-4 disabled:opacity-40" :disabled="loading || page >= pages" @click="$emit('change', page + 1)">下一页</button></div></nav>
</template>
