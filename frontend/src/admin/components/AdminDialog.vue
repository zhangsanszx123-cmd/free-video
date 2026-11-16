<script setup>
import { onMounted, onUnmounted, ref, useId } from 'vue'
import Icon from '../../components/Icon.vue'
const props = defineProps({ title: String, busy: Boolean, wide: Boolean })
const emit = defineEmits(['close'])
const dialog = ref(null), titleId = useId()
let overflow = '', pressedOutside = false
function outside(event) {
  const b = dialog.value.getBoundingClientRect()
  return event.clientX < b.left || event.clientX > b.right || event.clientY < b.top || event.clientY > b.bottom
}
function close() { if (!props.busy) emit('close') }
onMounted(() => { overflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; dialog.value.showModal() })
onUnmounted(() => { document.body.style.overflow = overflow })
</script>
<template>
  <dialog ref="dialog" :aria-labelledby="titleId" class="upgrade-dialog m-auto w-[calc(100%-2rem)] rounded-2xl bg-white p-0 shadow-2xl" :class="wide ? 'max-w-2xl' : 'max-w-md'"
    @cancel.prevent="close" @pointerdown="pressedOutside = $event.target === dialog && outside($event)" @click="if (pressedOutside && $event.target === dialog && outside($event)) close(); pressedOutside = false">
    <div class="p-5 sm:p-6"><header class="mb-5 flex items-center justify-between gap-4"><h2 :id="titleId" class="text-lg font-bold text-slate-950">{{ title }}</h2><button type="button" aria-label="关闭对话框" class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100 disabled:opacity-50" :disabled="busy" @click="close"><Icon name="x" /></button></header><slot /></div>
  </dialog>
</template>
