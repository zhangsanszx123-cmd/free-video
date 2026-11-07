<script setup>
import { ref } from 'vue'
import Icon from './Icon.vue'

defineProps({ items: { type: Array, required: true } })
const openIdx = ref(0)
</script>

<template>
  <div class="mx-auto max-w-3xl divide-y divide-slate-200 overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <div v-for="(item, i) in items" :key="item.q">
      <button class="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-sm font-semibold text-slate-900 hover:bg-slate-50 sm:text-base"
        :aria-expanded="openIdx === i" @click="openIdx = openIdx === i ? -1 : i">
        {{ item.q }}
        <Icon name="chevron" :size="18" class="shrink-0 text-slate-400 transition" :class="{ 'rotate-180 text-indigo-500': openIdx === i }" />
      </button>
      <div v-show="openIdx === i" class="px-5 pb-4 text-sm leading-relaxed text-slate-600">{{ item.a }}</div>
    </div>
  </div>
</template>
