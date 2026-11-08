<script setup>
const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 18 },
})

const paths = {
  sparkles: ['M9.94 14.06 8 20l-1.94-5.94L0 12l6.06-1.94L8 4l1.94 6.06L16 12z', 'M20 3v4', 'M22 5h-4', 'M18 15v4', 'M20 17h-4'],
  mindmap: ['M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M18 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4z', 'M18 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z', 'M18 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4z', 'M9 6h3a2 2 0 0 1 2 2v9a2 2 0 0 0 2 2', 'M12 6h4', 'M14 12h2'],
  chat: ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z', 'M8 9h8', 'M8 13h5'],
  send: ['M22 2 11 13', 'M22 2 15 22l-4-9-9-4 20-7z'],
  search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'M21 21l-4.35-4.35'],
  plus: ['M12 5v14', 'M5 12h14'],
  minus: ['M5 12h14'],
  expand: ['M15 3h6v6', 'M9 21H3v-6', 'M21 3l-7 7', 'M3 21l7-7'],
  refresh: ['M21 2v6h-6', 'M3 12a9 9 0 0 1 15-6.7L21 8', 'M3 22v-6h6', 'M21 12a9 9 0 0 1-15 6.7L3 16'],
  copy: ['M8 8h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2z', 'M16 8V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  external: ['M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6', 'M15 3h6v6', 'M10 14 21 3'],
  play: ['M6 3l14 9-14 9V3z'],
  check: ['M20 6 9 17l-5-5'],
  alert: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 8v4', 'M12 16h.01'],
  loader: ['M21 12a9 9 0 1 1-6.22-8.56'],
  book: ['M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z', 'M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z'],
  compass: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M16.24 7.76l-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12z'],
  trash: ['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6', 'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'],
  code: ['M16 18l6-6-6-6', 'M8 6l-6 6 6 6'],
  link: ['M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71', 'M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71'],
  clipboard: ['M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z', 'M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2'],
}
</script>

<template>
  <svg :width="props.size" :height="props.size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path v-for="d in paths[props.name] || []" :key="d" :d="d" />
  </svg>
</template>
