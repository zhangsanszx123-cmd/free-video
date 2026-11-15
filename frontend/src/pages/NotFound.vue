<script setup>
import Icon from '../components/Icon.vue'
</script>

<template>
  <section class="hero-bg flex min-h-[calc(100dvh-4rem)] items-center px-4 py-16">
    <div class="mx-auto max-w-md text-center">
      <span class="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-200"><Icon name="alert" :size="26" /></span>
      <p class="mt-5 text-sm font-bold text-indigo-600">404</p>
      <h1 class="mt-1 text-2xl font-extrabold tracking-tight text-slate-950 sm:text-3xl">没有找到这个页面</h1>
      <p class="mt-3 text-sm leading-6 text-slate-600">链接可能已失效或输入有误，可以回到首页重新粘贴视频链接。</p>
      <div class="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
        <RouterLink to="/" class="btn-primary inline-flex min-h-11 items-center justify-center rounded-xl px-6 font-bold">返回首页</RouterLink>
        <RouterLink to="/pricing" class="btn-ghost inline-flex min-h-11 items-center justify-center px-6 font-semibold">查看会员套餐</RouterLink>
      </div>
    </div>
  </section>
</template>
