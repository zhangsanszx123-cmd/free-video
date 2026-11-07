<template>
  <footer class="border-t border-slate-200 bg-white pb-24 pt-12 md:pb-10">
    <div class="mx-auto grid max-w-7xl gap-8 px-4 sm:px-6 md:grid-cols-4">
      <div class="md:col-span-2">
        <div class="flex items-center gap-2">
          <img src="/logo.svg" alt="" class="h-7 w-7" />
          <span class="text-lg font-extrabold">Free<span class="text-grad">Video</span></span>
        </div>
        <p class="mt-3 max-w-md text-sm leading-relaxed text-slate-500">
          FreeVideo 基于开源项目 <a href="https://github.com/yt-dlp/yt-dlp" target="_blank" rel="noopener" class="text-indigo-600 hover:underline">yt-dlp</a>
          构建，支持 1800+ 站点的视频、音频、字幕下载，以及 AI 视频总结与字幕翻译。
        </p>
        <p class="mt-3 max-w-md text-xs leading-relaxed text-slate-400">
          本站仅供个人学习与研究使用，请尊重版权，勿下载或传播未经授权的内容；下载内容的版权归原作者所有。本站不存储任何视频，临时文件 30 分钟后自动删除。
        </p>
      </div>
      <div>
        <h4 class="text-sm font-semibold text-slate-900">工具</h4>
        <ul class="mt-3 space-y-2 text-sm text-slate-500">
          <li><RouterLink to="/" class="hover:text-indigo-600">视频下载</RouterLink></li>
          <li><RouterLink to="/" class="hover:text-indigo-600">MP3 音频提取</RouterLink></li>
          <li><RouterLink to="/batch" class="hover:text-indigo-600">批量下载 ZIP</RouterLink></li>
          <li><RouterLink to="/ai" class="hover:text-indigo-600">AI 视频总结 / 字幕翻译</RouterLink></li>
        </ul>
      </div>
      <div>
        <h4 class="text-sm font-semibold text-slate-900">帮助</h4>
        <ul class="mt-3 space-y-2 text-sm text-slate-500">
          <li><RouterLink to="/#steps" class="hover:text-indigo-600">使用说明</RouterLink></li>
          <li><RouterLink to="/#faq" class="hover:text-indigo-600">常见问题</RouterLink></li>
          <li><RouterLink to="/pricing" class="hover:text-indigo-600">会员定价</RouterLink></li>
        </ul>
      </div>
    </div>
    <div class="mx-auto mt-10 max-w-7xl px-4 text-xs text-slate-400 sm:px-6">© {{ new Date().getFullYear() }} FreeVideo · 学习项目 · Powered by yt-dlp</div>
  </footer>
</template>
