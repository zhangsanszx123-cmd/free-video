<script setup>
import { onUnmounted, ref, watch } from 'vue'
import Icon from './Icon.vue'
import { ui } from '../store.js'

const dialog = ref(null)
let previousOverflow = ''
function trapFocus(event) {
  if (event.key !== 'Tab') return
  const controls = [...dialog.value.querySelectorAll('button, a[href], input, select, textarea, [tabindex="0"]')]
    .filter((el) => !el.disabled && el.getClientRects().length)
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}
watch(() => ui.upgradeOpen, (open) => {
  if (open) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.value?.showModal()
  } else {
    dialog.value?.close()
    document.body.style.overflow = previousOverflow
  }
}, { flush: 'post' })
onUnmounted(() => { document.body.style.overflow = previousOverflow })
</script>

<template>
    <dialog ref="dialog" aria-labelledby="upgrade-title" aria-describedby="upgrade-description"
      class="upgrade-dialog m-auto w-[calc(100%-2rem)] max-w-md rounded-3xl bg-white p-0 shadow-2xl"
      @keydown="trapFocus" @close="ui.upgradeOpen = false" @cancel.prevent="ui.upgradeOpen = false"
      @click.self="ui.upgradeOpen = false">
      <div class="p-6">
        <div class="flex items-start justify-between">
          <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-300 to-orange-500 text-white shadow-lg">
            <Icon name="gift" :size="24" />
          </span>
          <button autofocus class="flex h-11 w-11 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100" aria-label="关闭" @click="ui.upgradeOpen = false"><Icon name="x" /></button>
        </div>
        <h3 id="upgrade-title" class="mt-4 text-xl font-bold text-slate-950">{{ ui.upgradeReason || '开通 Pro' }}功能即将上线</h3>
        <p id="upgrade-description" class="mt-2 text-sm leading-relaxed text-slate-500">
          在线支付暂未开放。<b class="text-slate-800">视频下载与平台字幕提取免费</b>；语音识别按会员月度额度扣除时长，免费用户也可登录后使用每月赠送额度。会员开通暂由管理员处理。
        </p>
        <ul class="mt-4 space-y-2 text-sm text-slate-700">
          <li v-for="t in ['视频下载、音频提取与平台字幕免费', '月度额度在北京时间每月 1 日重置', '任务记录与转录文本保存 30 天', '已有文稿复制和导出不重复扣时长']" :key="t" class="flex items-center gap-2">
            <Icon name="check" :size="16" class="text-emerald-500" /> {{ t }}
          </li>
        </ul>
        <button class="btn-primary mt-6 w-full rounded-xl py-3 font-bold" @click="ui.upgradeOpen = false">好的，先免费体验</button>
      </div>
    </dialog>
</template>
