<script setup>
import Icon from './Icon.vue'

defineProps({ title: { type: String, required: true }, subtitle: { type: String, default: '' } })
const perks = [
  { icon: 'layers', text: '批量提取：最多 20 条链接，字幕/视频一键打包' },
  { icon: 'sparkles', text: 'AI 总结：结构化大纲、思维导图与视频追问' },
  { icon: 'shield', text: '账号仅保存用户名与加密密码，不关联任何第三方平台账号' },
]
</script>

<template>
  <section class="hero-bg relative min-h-[calc(100dvh-4rem)] overflow-hidden px-4 py-10 sm:py-16">
    <div class="pointer-events-none absolute -left-24 top-16 h-72 w-72 rounded-full bg-blue-400/20 blur-3xl"></div>
    <div class="pointer-events-none absolute -right-24 bottom-10 h-72 w-72 rounded-full bg-violet-400/20 blur-3xl"></div>
    <div class="relative mx-auto grid max-w-5xl items-center gap-10 lg:grid-cols-[1fr_440px]">
      <div class="hidden lg:block">
        <h1 class="text-4xl font-extrabold leading-tight tracking-tight text-slate-950">
          登录 <span class="text-grad">FreeVideo</span><br />解锁批量提取与 AI 总结
        </h1>
        <p class="mt-4 text-slate-600">注册免费，登录后即可使用批量提取、AI 总结与每月语音识别额度。</p>
        <ul class="mt-8 space-y-4">
          <li v-for="p in perks" :key="p.text" class="flex items-center gap-3 text-slate-700">
            <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/80 text-indigo-600 shadow-sm ring-1 ring-indigo-100">
              <Icon :name="p.icon" :size="18" />
            </span>
            {{ p.text }}
          </li>
        </ul>
      </div>
      <div class="glass-card mx-auto w-full max-w-[440px] rounded-3xl p-6 sm:p-8">
        <h2 class="text-2xl font-extrabold tracking-tight text-slate-950">{{ title }}</h2>
        <p v-if="subtitle" class="mt-1.5 text-sm text-slate-500">{{ subtitle }}</p>
        <slot />
      </div>
    </div>
  </section>
</template>
