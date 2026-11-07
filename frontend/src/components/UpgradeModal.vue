<script setup>
import Icon from './Icon.vue'
import { ui } from '../store.js'
</script>

<template>
  <Transition enter-from-class="opacity-0" leave-to-class="opacity-0" enter-active-class="transition" leave-active-class="transition">
    <div v-if="ui.upgradeOpen" class="fixed inset-0 z-[60] flex items-end justify-center bg-slate-950/50 p-4 backdrop-blur-sm sm:items-center"
      @click.self="ui.upgradeOpen = false">
      <div class="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl">
        <div class="flex items-start justify-between">
          <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-300 to-orange-500 text-white shadow-lg">
            <Icon name="gift" :size="24" />
          </span>
          <button class="p-1 text-slate-400 hover:text-slate-600" aria-label="关闭" @click="ui.upgradeOpen = false"><Icon name="x" /></button>
        </div>
        <h3 class="mt-4 text-xl font-bold text-slate-950">{{ ui.upgradeReason || '开通 Pro' }}功能即将上线</h3>
        <p class="mt-2 text-sm leading-relaxed text-slate-500">
          当前为学习演示版本，账号与在线支付尚未接入。<b class="text-slate-800">所有功能目前免费开放</b>，欢迎直接体验 4K 下载、批量 ZIP 与 AI 总结！
        </p>
        <ul class="mt-4 space-y-2 text-sm text-slate-700">
          <li v-for="t in ['4K/8K 原画质，音视频自动合并', '批量下载 20 条，一键打包 ZIP', 'AI 视频总结 + 双语字幕翻译', '多任务并行，专属高速通道']" :key="t" class="flex items-center gap-2">
            <Icon name="check" :size="16" class="text-emerald-500" /> {{ t }}
          </li>
        </ul>
        <button class="btn-primary mt-6 w-full rounded-xl py-3 font-bold" @click="ui.upgradeOpen = false">好的，先免费体验</button>
      </div>
    </div>
  </Transition>
</template>
