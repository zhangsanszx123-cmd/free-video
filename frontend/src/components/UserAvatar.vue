<script setup>
import { computed } from 'vue'

const props = defineProps({ name: { type: String, default: '' }, size: { type: Number, default: 32 } })
const palette = ['from-blue-500 to-indigo-600', 'from-violet-500 to-purple-600', 'from-emerald-500 to-teal-600', 'from-amber-500 to-orange-600', 'from-rose-500 to-pink-600']
const initial = computed(() => ([...props.name.trim()][0] || '?').toUpperCase())
const tone = computed(() => palette[[...props.name].reduce((sum, c) => sum + c.codePointAt(0), 0) % palette.length])
</script>

<template>
  <span aria-hidden="true" class="inline-flex shrink-0 select-none items-center justify-center rounded-full bg-gradient-to-br font-bold text-white shadow-sm"
    :class="tone" :style="{ width: `${props.size}px`, height: `${props.size}px`, fontSize: `${Math.round(props.size * 0.42)}px` }">
    {{ initial }}
  </span>
</template>
