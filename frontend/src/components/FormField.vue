<script setup>
import { ref, useId } from 'vue'
import Icon from './Icon.vue'

const model = defineModel({ type: String, default: '' })
const props = defineProps({
  label: { type: String, required: true },
  type: { type: String, default: 'text' },
  icon: { type: String, default: '' },
  autocomplete: { type: String, default: 'off' },
  placeholder: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  maxlength: { type: [Number, String], default: undefined },
  disabled: { type: Boolean, default: false },
  autofocus: { type: Boolean, default: false },
})
const id = useId()
const reveal = ref(false)
</script>

<template>
  <div>
    <label :for="id" class="mb-1.5 block text-sm font-semibold text-slate-700">{{ props.label }}</label>
    <div class="relative">
      <Icon v-if="props.icon" :name="props.icon" :size="18" class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
      <input :id="id" v-model="model" :type="props.type === 'password' && reveal ? 'text' : props.type"
        :autocomplete="props.autocomplete" :placeholder="props.placeholder" :maxlength="props.maxlength" :disabled="props.disabled" :autofocus="props.autofocus"
        :aria-invalid="Boolean(props.error)" :aria-describedby="props.error || props.hint ? `${id}-desc` : undefined"
        class="input-control min-h-12 w-full rounded-xl py-3 pr-12 text-sm text-slate-900 placeholder-slate-400 disabled:opacity-60"
        :class="[props.icon ? 'pl-10' : 'pl-3.5', props.error ? '!border-rose-300' : '']" />
      <button v-if="props.type === 'password'" type="button"
        class="absolute right-1 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 hover:text-indigo-600"
        :aria-label="reveal ? '隐藏密码' : '显示密码'" :aria-pressed="reveal" @click="reveal = !reveal">
        <Icon :name="reveal ? 'eyeOff' : 'eye'" :size="18" />
      </button>
    </div>
    <p v-if="props.error || props.hint" :id="`${id}-desc`" class="mt-1 text-xs" :class="props.error ? 'text-rose-600' : 'text-slate-400'">
      {{ props.error || props.hint }}
    </p>
  </div>
</template>
