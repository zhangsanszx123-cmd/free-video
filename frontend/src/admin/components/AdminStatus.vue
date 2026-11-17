<script setup>
defineProps({ status: String })
</script>
<template><span class="admin-badge" :class="status === 'active' ? 'admin-badge--ok' : 'admin-badge--bad'">{{ status === 'active' ? '已启用' : '已禁用' }}</span></template>
