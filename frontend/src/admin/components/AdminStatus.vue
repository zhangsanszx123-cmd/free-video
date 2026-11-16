<script setup>
defineProps({ status: String })
</script>
<template><span class="inline-flex rounded-md px-2 py-1 text-xs font-semibold" :class="status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'">{{ status === 'active' ? '已启用' : '已禁用' }}</span></template>
